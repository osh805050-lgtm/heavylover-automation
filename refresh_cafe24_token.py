"""카페24 OAuth refresh_token 자동 갱신.

매일 04:00에 cron으로 실행. refresh_access_token() 호출 시
새 access_token + 새 refresh_token이 동시 발급되어 만료 시계가 리셋됨.
이렇게 두면 refresh_token 자체 만료(2주)가 도래하기 전 매일 새로워져
영구적으로 OAuth 살아있게 됨.

실패 시 텔레그램 알림.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cafe24_client
from telegram_client import send_message

KST = timezone(timedelta(hours=9))


def main():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    try:
        new_token = cafe24_client.refresh_access_token()
        prefix = new_token[:8]
        msg = f"✅ 카페24 OAuth 자동 갱신 완료 ({now})\nnew access_token: {prefix}..."
        print(msg)
        # 성공 시엔 텔레그램 보내지 않음 (소음 줄이려고)
        return 0
    except Exception as e:
        msg = f"🚨 카페24 OAuth 자동 갱신 실패 ({now})\n{e}\n→ 수동 재발급 필요"
        print(msg)
        try:
            send_message(msg, channel="ops")
        except Exception as notify_err:
            # Codex review 2026-05-10: 알림 실패도 silent 안 됨. stderr에 명시 + 비zero exit는 유지
            print(
                f"⚠️ 텔레그램 알림 실패: {notify_err}\n"
                f"→ 카페24 OAuth 갱신도 실패한 상태이므로 ops 채널 점검 필요",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
