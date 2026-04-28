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
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.telegram.org"

VALID_CHANNELS = ("ops", "report", "ads", "govt")


def _get_env(channel: str = "ops") -> dict:
    load_dotenv(ENV_PATH, override=True)
    ch = (channel or "ops").lower()
    if ch not in VALID_CHANNELS:
        ch = "ops"
    suffix = ch.upper()
    token = os.getenv(f"TELEGRAM_BOT_TOKEN_{suffix}") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv(f"TELEGRAM_CHAT_ID_{suffix}") or os.getenv("TELEGRAM_CHAT_ID")
    return {"channel": ch, "token": token, "chat_id": chat_id}


def send_message(text: str, channel: str = "ops") -> bool:
    """텔레그램으로 메시지 전송. channel 미지정 시 ops(기본 = 기존 단일 봇)."""
    env = _get_env(channel)
    if not env["token"] or not env["chat_id"]:
        print(f"⚠️ telegram[{env['channel']}] 토큰/chat_id 없음 — 발송 생략")
        return False
    r = requests.post(
        f"{API_BASE}/bot{env['token']}/sendMessage",
        json={"chat_id": env["chat_id"], "text": text},
        timeout=30,
    )
    return r.ok


def send_document(file_path, caption: str = "", channel: str = "ops") -> bool:
    """텔레그램으로 파일 전송 (엑셀 등)"""
    env = _get_env(channel)
    if not env["token"] or not env["chat_id"]:
        print(f"⚠️ telegram[{env['channel']}] 토큰/chat_id 없음 — 발송 생략")
        return False
    with open(file_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/bot{env['token']}/sendDocument",
            data={"chat_id": env["chat_id"], "caption": caption},
            files={"document": f},
            timeout=120,
        )
    return r.ok


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
            ok = send_message(f"[{ch}] 테스트 메시지 — 모듈 정상 작동", channel=ch)
            print(f"  {ch}: 전송 {'OK' if ok else 'FAIL'}")
        else:
            print(f"  {ch}: 토큰/chat_id 없음 (스킵)")
