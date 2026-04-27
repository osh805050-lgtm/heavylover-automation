"""텔레그램 봇 모듈 - 알림 + 파일 전송 + 명령어 대기"""

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.telegram.org"


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    return {
        "token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
    }


def send_message(text):
    """텔레그램으로 메시지 전송"""
    env = _get_env()
    r = requests.post(
        f"{API_BASE}/bot{env['token']}/sendMessage",
        json={"chat_id": env["chat_id"], "text": text},
        timeout=30,
    )
    return r.ok


def send_document(file_path, caption=""):
    """텔레그램으로 파일 전송 (엑셀 등)"""
    env = _get_env()
    with open(file_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/bot{env['token']}/sendDocument",
            data={"chat_id": env["chat_id"], "caption": caption},
            files={"document": f},
            timeout=120,
        )
    return r.ok


def _get_latest_update_id():
    env = _get_env()
    r = requests.get(f"{API_BASE}/bot{env['token']}/getUpdates", timeout=30)
    if not r.ok:
        return 0
    updates = r.json().get("result", [])
    if not updates:
        return 0
    return updates[-1]["update_id"]


def wait_for_command(commands, timeout_seconds=7200, poll_interval=10):
    """사장님이 텔레그램으로 보낸 특정 명령어를 대기 (polling)

    Args:
        commands: 대기할 명령어 리스트 (예: ["/done", "/cancel"])
        timeout_seconds: 최대 대기 시간 (기본 2시간)
        poll_interval: 폴링 간격 (초, 기본 10초)

    Returns:
        str: 받은 명령어 (예: "/done") 또는 None (타임아웃)
    """
    env = _get_env()
    # 기존 메시지들은 무시하고, 이후 메시지부터 대기
    last_update_id = _get_latest_update_id()

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
            # 네트워크 일시 장애 등 무시하고 계속
            continue

    return None


if __name__ == "__main__":
    # 간단 테스트
    print("텔레그램 연결 테스트...")
    ok = send_message("테스트 메시지 - 모듈 정상 작동")
    print(f"전송 결과: {ok}")
