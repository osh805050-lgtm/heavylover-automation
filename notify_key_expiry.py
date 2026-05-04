"""API 키 만료 사전 알림 — run.sh에서 매일 실행"""

from datetime import date
from pathlib import Path

import telegram_client

# (만료일, 사전 알림 일수, 설명)
KEY_EXPIRY = [
    (date(2026, 10, 31), 10, "쿠팡 Wing API 키 (Wing 판매자센터에서 재발급)"),
]

today = date.today()

for expire_date, days_before, description in KEY_EXPIRY:
    notify_date = expire_date - __import__("datetime").timedelta(days=days_before)
    if today == notify_date:
        msg = (
            f"[API 키 만료 {days_before}일 전]\n"
            f"{description}\n"
            f"만료일: {expire_date}"
        )
        telegram_client.send_message(msg, channel="ops")
