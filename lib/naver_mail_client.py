"""네이버 메일 IMAP 클라이언트 - 정부지원 공고 메일 스캔 (Layer 2 교차검증)

전제:
  - 네이버 메일 환경설정 → POP3/IMAP 설정에서 IMAP 사용 ON
  - 2단계 인증 ON + 애플리케이션 비밀번호 발급 완료
  - .env에 NAVER_MAIL_USER, NAVER_MAIL_APP_PASSWORD 등록

사용:
  from lib.naver_mail_client import scan_govt_announcements
  hits = scan_govt_announcements(days_back=1)
"""

import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
IMAP_HOST = "imap.naver.com"
IMAP_PORT = 993
KST = timezone(timedelta(hours=9))

# 정부지원 공고 메일 식별 키워드 (제목·본문 매칭)
SUBJECT_KEYWORDS = [
    "지원사업", "공고", "모집공고", "신청", "선정", "사업공고",
    "지원공고", "모집안내", "사업안내", "사업참여", "지원안내",
    "바우처", "사업계획", "수출지원", "창업지원",
]

# 신뢰할 수 있는 발신 도메인 (정부·진흥원·공공기관)
TRUSTED_SENDERS = [
    ".go.kr", ".or.kr",
    "k-startup", "kised", "kotra", "nipa", "bizinfo",
    "mss.go.kr", "sbiz24", "smes.go.kr",
    "kibo", "kosmes", "kibwa",
    "gbsa", "gg.go.kr", "yongin", "ypa.or.kr",
    "중소벤처", "창업진흥원", "기업마당", "소상공인",
]

# 노이즈 발신자/도메인 (즉시 제외 — 2026-04-27 실측 기반)
NOISE_DOMAINS = [
    ".ac.kr",           # 학교 (세종사이버대 등)
    "hanacard",         # 카드사 안내
    "navercorp.com",    # 스마트스토어 운영 알림
    "duse.co.kr",       # 부동산 약관
    "linkprice",        # 광고 제휴
    "postman.co.kr",    # 마케팅 발송 대행
    "directsend",       # 마케팅 발송 대행 (단, ypa는 directsend 사용 — 별도 처리)
    "tason.com",        # 광고 발송 대행
    "no-reply@",        # 자동 발송 광고 일반
]

# 노이즈 키워드 (제목에 있으면 제외)
NOISE_SUBJECT_KEYWORDS = [
    "약관", "개정 안내", "이용약관",
    "보험", "카드", "쇼핑라이브",
    "프로모션", "할인", "쿠폰",
    "빠른정산", "정산 안내",
    "(광고)",
]


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    user = os.getenv("NAVER_MAIL_USER")
    pw = os.getenv("NAVER_MAIL_APP_PASSWORD")
    if not user or not pw:
        raise RuntimeError(
            "NAVER_MAIL_USER, NAVER_MAIL_APP_PASSWORD가 .env에 없습니다. "
            "docs/govt-radar/01-naver-mail-setup.md 참고."
        )
    return {"user": user, "password": pw.replace(" ", "")}


def _decode_header_value(raw):
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []
        self._skip = 0
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self._href = v

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip > 0:
            self._skip -= 1
        if tag == "a":
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if text:
            self.parts.append(text)
            if self._href:
                self.links.append(self._href)


def _extract_body(msg):
    """메일 본문에서 텍스트 + 링크 추출"""
    text_parts = []
    links = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if ctype == "text/plain":
                text_parts.append(content)
                links.extend(re.findall(r"https?://[^\s)]+", content))
            elif ctype == "text/html":
                parser = _TextExtractor()
                parser.feed(content)
                text_parts.append(" ".join(parser.parts))
                links.extend(parser.links)
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            content = ""
        if msg.get_content_type() == "text/html":
            parser = _TextExtractor()
            parser.feed(content)
            text_parts.append(" ".join(parser.parts))
            links.extend(parser.links)
        else:
            text_parts.append(content)
            links.extend(re.findall(r"https?://[^\s)]+", content))

    body = " ".join(p for p in text_parts if p).strip()
    body = re.sub(r"\s+", " ", body)
    return body, list(dict.fromkeys(links))  # 링크 중복 제거


def _is_govt_mail(subject, sender, body):
    """정부지원 공고로 판단되는 메일인지

    원칙: 누락 방지 우선, 그 다음 노이즈 제거.
    1. 신뢰 발신자(.go.kr, .or.kr 등) → 통과
    2. 그 외에는 노이즈 발신자/제목이면 제외
    3. 노이즈가 아니고 키워드가 있으면 통과
    """
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    # 1. 신뢰 도메인은 무조건 통과 (단, ypa.or.kr이 directsend 경유해도 OK)
    if any(t.lower() in sender_lower for t in TRUSTED_SENDERS):
        # 단, 신뢰 도메인이라도 명백한 노이즈 키워드면 제외
        if any(nk in subject for nk in ["약관", "이용약관", "개인정보처리방침"]):
            return False
        return True

    # 2. 노이즈 발신자 → 제외
    if any(nd in sender_lower for nd in NOISE_DOMAINS):
        return False

    # 3. 노이즈 제목 → 제외
    if any(nk in subject for nk in NOISE_SUBJECT_KEYWORDS):
        return False

    # 4. 키워드 매칭 (마지막 보루)
    text = f"{subject} {body[:500]}".lower()
    return any(k in text for k in SUBJECT_KEYWORDS)


def _extract_deadline(text):
    """본문에서 마감일 추출 — 발견 못하면 None (창작 금지)"""
    patterns = [
        r"마감[\s:]*(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})",
        r"신청기한[\s:]*(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})",
        r"접수마감[\s:]*(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})",
        r"~[\s]*(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except (ValueError, IndexError):
                continue
    return None


def scan_govt_announcements(days_back=1, mailbox="INBOX", verbose=False):
    """정부지원 공고 메일 스캔

    Args:
        days_back: 며칠 전부터 스캔 (기본 1 = 어제 이후)
        mailbox: IMAP 폴더명 (기본 INBOX)
        verbose: 진행 로그 출력

    Returns:
        list[dict]: [{
            "subject": str,
            "sender": str,
            "received_at": "YYYY-MM-DD HH:MM" (KST),
            "body_excerpt": str (앞 500자),
            "links": list[str],
            "deadline": str | None ("YYYY-MM-DD"),
            "source": "naver_mail",
        }, ...]
    """
    env = _get_env()
    results = []

    since_date = (datetime.now(KST) - timedelta(days=days_back)).strftime("%d-%b-%Y")

    if verbose:
        print(f"[naver_mail] 접속 중: {env['user']}@naver.com")

    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
        try:
            imap.login(env["user"], env["password"])
        except imaplib.IMAP4.error as e:
            raise RuntimeError(
                f"네이버 메일 로그인 실패: {e}. "
                "앱 비밀번호 만료 가능성 — 재발급 필요. "
                "docs/govt-radar/01-naver-mail-setup.md STEP 3 참고."
            )

        imap.select(mailbox, readonly=True)
        status, data = imap.search(None, f'(SINCE "{since_date}")')
        if status != "OK" or not data or not data[0]:
            if verbose:
                print(f"[naver_mail] 최근 {days_back}일 메일 없음")
            imap.logout()
            return results

        msg_ids = data[0].split()
        if verbose:
            print(f"[naver_mail] 최근 {days_back}일 메일 {len(msg_ids)}건 — 필터링 중")

        for mid in msg_ids:
            status, msg_data = imap.fetch(mid, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode_header_value(msg.get("Subject", ""))
            sender = _decode_header_value(msg.get("From", ""))
            date_raw = msg.get("Date", "")

            try:
                received_dt = email.utils.parsedate_to_datetime(date_raw)
                received_kst = received_dt.astimezone(KST)
                received_at = received_kst.strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                received_at = ""

            body, links = _extract_body(msg)

            if not _is_govt_mail(subject, sender, body):
                continue

            deadline = _extract_deadline(f"{subject} {body}")

            results.append({
                "subject": subject.strip(),
                "sender": sender.strip(),
                "received_at": received_at,
                "body_excerpt": body[:500],
                "links": links[:10],
                "deadline": deadline,
                "source": "naver_mail",
            })

        imap.logout()

    if verbose:
        print(f"[naver_mail] 정부지원 공고 후보: {len(results)}건")

    return results


def test_connection():
    """연결 테스트만 수행 — 메일 안 읽음"""
    env = _get_env()
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(env["user"], env["password"])
            imap.select("INBOX", readonly=True)
            status, data = imap.search(None, "ALL")
            count = len(data[0].split()) if data and data[0] else 0
            imap.logout()
        return {"ok": True, "user": env["user"], "inbox_total": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        result = test_connection()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
        hits = scan_govt_announcements(days_back=days, verbose=True)
        print(f"\n=== 결과 {len(hits)}건 ===")
        for h in hits:
            print(f"\n[{h['received_at']}] {h['subject']}")
            print(f"  발신: {h['sender']}")
            print(f"  마감: {h['deadline'] or '미상'}")
            print(f"  본문 앞: {h['body_excerpt'][:120]}...")
            if h["links"]:
                print(f"  링크: {h['links'][0]}")
