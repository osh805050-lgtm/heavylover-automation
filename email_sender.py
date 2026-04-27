"""
SMTP 이메일 발송 유틸

환경변수:
    SMTP_HOST       기본 smtp.gmail.com
    SMTP_PORT       기본 587 (STARTTLS)
    SMTP_USER       발송 계정 (예: osh805050@gmail.com)
    SMTP_PASSWORD   Gmail은 "앱 비밀번호" (일반 비밀번호 불가)
    EMAIL_FROM      발신자 (미설정 시 SMTP_USER 사용)
    EMAIL_TO        수신자 (쉼표로 여러 명 가능)
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    user = os.getenv("SMTP_USER", "")
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_addr": os.getenv("EMAIL_FROM") or user,
        "to_addrs": [
            a.strip() for a in (os.getenv("EMAIL_TO", "") or "").split(",") if a.strip()
        ],
    }


def send_email(subject, text_body, html_body=None):
    """이메일 발송. 성공 시 True, 실패 시 예외.

    Args:
        subject: 제목
        text_body: 일반 텍스트 본문 (폴백)
        html_body: HTML 본문 (선택)
    """
    env = _get_env()
    if not env["user"] or not env["password"]:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD 환경변수 없음")
    if not env["to_addrs"]:
        raise RuntimeError("EMAIL_TO 환경변수 없음")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["from_addr"]
    msg["To"] = ", ".join(env["to_addrs"])
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(env["host"], env["port"], timeout=30) as smtp:
        smtp.starttls(context=context)
        smtp.login(env["user"], env["password"])
        smtp.send_message(msg)

    return True


if __name__ == "__main__":
    # 간단 테스트
    ok = send_email(
        subject="[테스트] email_sender.py",
        text_body="SMTP 연결 테스트입니다.",
        html_body="<p>SMTP 연결 <b>테스트</b>입니다.</p>",
    )
    print(f"send_email 결과: {ok}")
