"""API 키 만료 사전 알림 — run.sh에서 매일 실행

알림 정책 (Codex review 2026-05-10):
- 만료 N일 전~만료일까지 매일 알림 (기존 D-N 하루만 → cron 1번 놓치면 알림 사라짐 문제 차단)
- 만료 후에도 매일 "이미 만료됨 X일째" 알림 (사후 통보 차단)
"""

from datetime import date

import telegram_client

# (만료일, 사전 알림 일수, 설명)
KEY_EXPIRY = [
    (date(2026, 10, 31), 10, "쿠팡 Wing API 키 (Wing 판매자센터에서 재발급)"),
]

today = date.today()

for expire_date, days_before, description in KEY_EXPIRY:
    days_left = (expire_date - today).days
    if days_left < 0:
        # 이미 만료
        msg = (
            f"🚨 [API 키 만료 {-days_left}일 경과]\n"
            f"{description}\n"
            f"만료일: {expire_date} → 즉시 재발급 필요"
        )
        telegram_client.send_message(msg, channel="ops")
    elif 0 <= days_left <= days_before:
        # 윈도우 내 알림 (D-N ~ D-day)
        msg = (
            f"[API 키 만료 {days_left}일 전]\n"
            f"{description}\n"
            f"만료일: {expire_date}"
        )
        telegram_client.send_message(msg, channel="ops")
