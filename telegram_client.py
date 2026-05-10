"""텔레그램 봇 모듈 - 채널별 봇 분리 + 알림·파일·명령어.

채널 4개:
- ops    : 운영(11시 발주·13시 송장·OAuth 갱신·자동화 오류). wait_for_command 가능.
- report : 재구매 매일 09:05 30초 요약 (읽기 전용)
- ads    : Meta 광고 일일/주간 KPI (읽기 전용)
- govt   : 정부지원 레이더 적합 공고 (읽기 전용)

.env 키 우선순위:
1. TELEGRAM_BOT_TOKEN_<CHANNEL_UPPER> + TELEGRAM_CHAT_ID_<CHANNEL_UPPER>
2. (fallback) TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  ← 단일 봇 환경 호환
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.telegram.org"

VALID_CHANNELS = ("ops", "report", "ads", "govt")


@dataclass
class TelegramResponse:
    """텔레그램 API 호출 결과.

    backward compat: `__bool__`이 ok를 반환하므로 기존 `if send_message(...)` 형태 호출자 그대로 작동.

    Fields:
        ok: 전송 성공 여부
        status_code: HTTP status (-1 = 토큰/chat_id 누락, 0 = 네트워크 예외, 200+ = 실제 응답)
        body: 응답 본문 또는 에러 사유
    """
    ok: bool
    status_code: int
    body: str

    def __bool__(self) -> bool:
        return self.ok


def _get_env(channel: str = "ops") -> dict:
    load_dotenv(ENV_PATH, override=True)
    ch = (channel or "ops").lower()
    if ch not in VALID_CHANNELS:
        raise ValueError(
            f"Invalid telegram channel '{channel}'. "
            f"Allowed: {VALID_CHANNELS}"
        )
    suffix = ch.upper()
    token = os.getenv(f"TELEGRAM_BOT_TOKEN_{suffix}") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv(f"TELEGRAM_CHAT_ID_{suffix}") or os.getenv("TELEGRAM_CHAT_ID")
    return {"channel": ch, "token": token, "chat_id": chat_id}


def _parse_retry_after(body_text: str, default: int = 1) -> int:
    """429 응답 body에서 parameters.retry_after 파싱. 실패 시 default."""
    try:
        import json
        data = json.loads(body_text)
        ra = data.get("parameters", {}).get("retry_after")
        if isinstance(ra, (int, float)) and ra > 0:
            return int(ra)
    except Exception:
        pass
    return default


def _post_with_retry(url: str, *, json_payload=None, data=None, files=None, timeout: int) -> TelegramResponse:
    """429 1회 재시도 + 영구 실패 stderr 로그 + 네트워크 예외 캡처."""
    try:
        r = requests.post(url, json=json_payload, data=data, files=files, timeout=timeout)
    except Exception as exc:
        return TelegramResponse(ok=False, status_code=0, body=str(exc))

    if r.ok:
        return TelegramResponse(ok=True, status_code=r.status_code, body=r.text)

    # 429: rate limit → retry_after 만큼 대기 후 1회 재시도
    if r.status_code == 429:
        retry_after = _parse_retry_after(r.text, default=1)
        sleep_s = min(retry_after, 30)
        print(
            f"⚠️ telegram 429 rate-limited, sleep {sleep_s}s then retry once",
            file=sys.stderr,
        )
        time.sleep(sleep_s)
        # files는 재사용 불가(스트림 소진) — 호출자가 files=None일 때만 안전
        # send_document는 files 사용하므로 별도 처리 필요. 여기서는 단순 재시도만 시도.
        try:
            r2 = requests.post(url, json=json_payload, data=data, files=files, timeout=timeout)
        except Exception as exc:
            return TelegramResponse(ok=False, status_code=0, body=str(exc))
        if r2.ok:
            return TelegramResponse(ok=True, status_code=r2.status_code, body=r2.text)
        print(
            f"⚠️ telegram retry failed status={r2.status_code} body={r2.text[:200]}",
            file=sys.stderr,
        )
        return TelegramResponse(ok=False, status_code=r2.status_code, body=r2.text)

    # 401/403/404 등 영구적 실패 → 즉시 반환 + stderr 로그
    print(
        f"⚠️ telegram permanent failure status={r.status_code} body={r.text[:200]}",
        file=sys.stderr,
    )
    return TelegramResponse(ok=False, status_code=r.status_code, body=r.text)


def send_message(text: str, channel: str = "ops") -> TelegramResponse:
    """텔레그램으로 메시지 전송. channel 미지정 시 ops(기본 = 기존 단일 봇).

    Returns: TelegramResponse (truthy/falsy로 평가 가능 — backward compat)
    """
    env = _get_env(channel)
    if not env["token"] or not env["chat_id"]:
        print(f"⚠️ telegram[{env['channel']}] 토큰/chat_id 없음 — 발송 생략")
        return TelegramResponse(ok=False, status_code=-1, body="missing_token_or_chat_id")

    url = f"{API_BASE}/bot{env['token']}/sendMessage"
    payload = {"chat_id": env["chat_id"], "text": text}
    return _post_with_retry(url, json_payload=payload, timeout=30)


def send_document(file_path, caption: str = "", channel: str = "ops") -> TelegramResponse:
    """텔레그램으로 파일 전송 (엑셀 등).

    Returns: TelegramResponse (truthy/falsy로 평가 가능 — backward compat)
    """
    env = _get_env(channel)
    if not env["token"] or not env["chat_id"]:
        print(f"⚠️ telegram[{env['channel']}] 토큰/chat_id 없음 — 발송 생략")
        return TelegramResponse(ok=False, status_code=-1, body="missing_token_or_chat_id")

    url = f"{API_BASE}/bot{env['token']}/sendDocument"

    # 파일 스트림은 1회 소진되므로 429 재시도 위해 두 번 열어 처리
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": env["chat_id"], "caption": caption},
                files={"document": f},
                timeout=120,
            )
    except Exception as exc:
        return TelegramResponse(ok=False, status_code=0, body=str(exc))

    if r.ok:
        return TelegramResponse(ok=True, status_code=r.status_code, body=r.text)

    if r.status_code == 429:
        retry_after = _parse_retry_after(r.text, default=1)
        sleep_s = min(retry_after, 30)
        print(
            f"⚠️ telegram 429 rate-limited (document), sleep {sleep_s}s then retry once",
            file=sys.stderr,
        )
        time.sleep(sleep_s)
        try:
            with open(file_path, "rb") as f:
                r2 = requests.post(
                    url,
                    data={"chat_id": env["chat_id"], "caption": caption},
                    files={"document": f},
                    timeout=120,
                )
        except Exception as exc:
            return TelegramResponse(ok=False, status_code=0, body=str(exc))
        if r2.ok:
            return TelegramResponse(ok=True, status_code=r2.status_code, body=r2.text)
        print(
            f"⚠️ telegram document retry failed status={r2.status_code} body={r2.text[:200]}",
            file=sys.stderr,
        )
        return TelegramResponse(ok=False, status_code=r2.status_code, body=r2.text)

    print(
        f"⚠️ telegram document permanent failure status={r.status_code} body={r.text[:200]}",
        file=sys.stderr,
    )
    return TelegramResponse(ok=False, status_code=r.status_code, body=r.text)


def _get_latest_update_id(channel: str = "ops") -> int:
    env = _get_env(channel)
    if not env["token"]:
        return 0
    r = requests.get(f"{API_BASE}/bot{env['token']}/getUpdates", timeout=30)
    if not r.ok:
        return 0
    updates = r.json().get("result", [])
    if not updates:
        return 0
    return updates[-1]["update_id"]


def wait_for_command(commands, timeout_seconds: int = 7200, poll_interval: int = 10, channel: str = "ops"):
    """사장님이 텔레그램으로 보낸 특정 명령어를 대기 (polling).

    Args:
        commands: 대기할 명령어 리스트 (예: ["/done", "/cancel"])
        timeout_seconds: 최대 대기 시간 (기본 2시간)
        poll_interval: 폴링 간격 (초, 기본 10초)
        channel: 어느 봇을 listen 할지 (기본 "ops")

    Returns:
        str: 받은 명령어 또는 None (타임아웃)
    """
    env = _get_env(channel)
    if not env["token"] or not env["chat_id"]:
        print(f"⚠️ telegram[{env['channel']}] 토큰/chat_id 없음 — wait 불가")
        return None

    last_update_id = _get_latest_update_id(channel)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            r = requests.get(
                f"{API_BASE}/bot{env['token']}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 20},
                timeout=30,
            )
            if not r.ok:
                continue

            updates = r.json().get("result", [])
            for update in updates:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = (msg.get("text") or "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id != env["chat_id"]:
                    continue

                if text in commands:
                    return text
        except Exception:
            continue

    return None


if __name__ == "__main__":
    # 4개 채널 모두 테스트
    print("텔레그램 4채널 연결 테스트...")
    for ch in VALID_CHANNELS:
        env = _get_env(ch)
        if env["token"] and env["chat_id"]:
            resp = send_message(f"[{ch}] 테스트 메시지 — 모듈 정상 작동", channel=ch)
            print(f"  {ch}: 전송 {'OK' if resp else 'FAIL'} (status={resp.status_code})")
        else:
            print(f"  {ch}: 토큰/chat_id 없음 (스킵)")
