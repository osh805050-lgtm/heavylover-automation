"""텔레그램 봇 4개 chat_id 자동 추출 + .env append.

사용법:
    1) BotFather에서 봇 3개(report·ads·govt) 생성
    2) 각 봇 username 검색 → /start 한 번 누르기 (chat_id 활성화)
    3) .env에 토큰 4개 입력:
       TELEGRAM_BOT_TOKEN_OPS=...      (기존 TELEGRAM_BOT_TOKEN 값 그대로)
       TELEGRAM_BOT_TOKEN_REPORT=...
       TELEGRAM_BOT_TOKEN_ADS=...
       TELEGRAM_BOT_TOKEN_GOVT=...
    4) python tools/setup_telegram_bots.py 실행 → chat_id 자동 추출 + .env append
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
API_BASE = "https://api.telegram.org"
CHANNELS = ("ops", "report", "ads", "govt")


def _get_token(channel: str) -> str | None:
    suffix = channel.upper()
    return os.getenv(f"TELEGRAM_BOT_TOKEN_{suffix}") or (os.getenv("TELEGRAM_BOT_TOKEN") if channel == "ops" else None)


def _existing_chat_id(channel: str) -> str | None:
    suffix = channel.upper()
    return os.getenv(f"TELEGRAM_CHAT_ID_{suffix}") or (os.getenv("TELEGRAM_CHAT_ID") if channel == "ops" else None)


def _fetch_chat_id(token: str) -> str | None:
    """getUpdates에서 가장 최근 사용자 메시지의 chat_id 추출."""
    try:
        r = requests.get(f"{API_BASE}/bot{token}/getUpdates", timeout=20)
        if not r.ok:
            return None
        updates = r.json().get("result", [])
        for u in reversed(updates):
            chat = u.get("message", {}).get("chat") or {}
            cid = chat.get("id")
            if cid:
                return str(cid)
    except Exception as e:
        print(f"  ⚠️ getUpdates 호출 실패: {e}")
    return None


def _send_test(token: str, chat_id: str, channel: str) -> bool:
    try:
        r = requests.post(
            f"{API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"✅ [{channel}] 봇 분리 테스트 — 정상 연결됨"},
            timeout=20,
        )
        return r.ok
    except Exception:
        return False


def _append_env(channel: str, chat_id: str) -> None:
    """이미 키가 있으면 갱신, 없으면 append."""
    suffix = channel.upper()
    key = f"TELEGRAM_CHAT_ID_{suffix}"
    new_line = f"{key}={chat_id}"
    if not ENV_PATH.exists():
        ENV_PATH.write_text(new_line + "\n", encoding="utf-8")
        return
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = new_line
            found = True
            break
    if not found:
        lines.append(new_line)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ENV_PATH, override=True)

    print("=" * 60)
    print("텔레그램 봇 4개 chat_id 자동 추출")
    print("=" * 60)

    success_count = 0
    skipped = []
    for ch in CHANNELS:
        print(f"\n[{ch}]")
        token = _get_token(ch)
        if not token:
            print(f"  ⚠️ TELEGRAM_BOT_TOKEN_{ch.upper()} 가 .env에 없음 — 스킵")
            skipped.append(ch)
            continue

        existing_cid = _existing_chat_id(ch)
        if existing_cid:
            print(f"  ✓ 기존 chat_id 발견: {existing_cid}")
            chat_id = existing_cid
        else:
            print(f"  → getUpdates 호출 중...")
            chat_id = _fetch_chat_id(token)
            if not chat_id:
                print(f"  ❌ chat_id 추출 실패. 봇에게 /start 또는 메시지 1번 보낸 뒤 다시 실행하세요.")
                skipped.append(ch)
                continue
            print(f"  ✓ chat_id 추출: {chat_id}")
            _append_env(ch, chat_id)
            print(f"  ✓ .env에 TELEGRAM_CHAT_ID_{ch.upper()} 저장")

        if _send_test(token, chat_id, ch):
            print(f"  ✅ 테스트 메시지 발송 성공")
            success_count += 1
        else:
            print(f"  ❌ 테스트 메시지 발송 실패")

    print("\n" + "=" * 60)
    print(f"결과: {success_count}/{len(CHANNELS)} 채널 성공")
    if skipped:
        print(f"미설정 채널: {', '.join(skipped)}")
        print("→ BotFather에서 봇 생성 + /start + .env에 토큰 추가 후 재실행")
    print("=" * 60)
    return 0 if success_count == len(CHANNELS) else 1


if __name__ == "__main__":
    sys.exit(main())
