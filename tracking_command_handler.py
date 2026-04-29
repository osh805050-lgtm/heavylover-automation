"""텔레그램 /tracking 명령 폴링 — 5분마다 cron 실행

/tracking 수신 시 tracking_register.run_from_excel() 호출.
last_processed_update_id로 중복 처리 방지.
"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import telegram_client
import tracking_register

ENV_PATH = Path(__file__).parent / ".env"
LAST_ID_PATH = Path(__file__).parent / "data" / "tracking_last_update_id.txt"


def _read_last_id():
    if not LAST_ID_PATH.exists():
        return 0
    try:
        return int(LAST_ID_PATH.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


def _save_last_id(uid):
    LAST_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_ID_PATH.write_text(str(uid), encoding="utf-8")


def _get_updates():
    load_dotenv(ENV_PATH, override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN_OPS") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return []
    last_id = _read_last_id()
    params = {"limit": 10, "timeout": 0}
    if last_id:
        params["offset"] = last_id + 1
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params=params,
        timeout=30,
    )
    if not r.ok:
        return []
    return r.json().get("result", [])


def main():
    updates = _get_updates()
    if not updates:
        return

    for update in updates:
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip().lower()
        if text == "/tracking":
            print(f"[{datetime.now():%H:%M:%S}] /tracking 수신 — 엑셀 등록 시작")
            tracking_register.run_from_excel()
            break  # 한 번 실행 후 중복 방지

    last_id = updates[-1]["update_id"]
    _save_last_id(last_id)


if __name__ == "__main__":
    main()
