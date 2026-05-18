"""정부지원 레이더 메인 파이프라인 (Layer 1+2+3)

흐름:
  1. Layer 1: 15개 1차 소스 크롤링 (govt_sources.fetch_all)
  2. Layer 2: 네이버 메일 IMAP 스캔 (naver_mail_client.scan_govt_announcements)
  3. 통합·중복제거 (dedupe.dedupe)
  4. 적합도 점수 (scorer.score_all)
  5. 텔레그램 알림 (적합도 ≥ 3)
  6. (옵션) Google Sheets 누적

실행:
  로컬: python govt_radar.py
  로컬 dry-run (텔레그램 발송 없이): python govt_radar.py --dry-run
  GitHub Actions: 매일 11:00 KST 자동
"""

import argparse
import io
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows 콘솔 UTF-8 강제 (이모지·한글 깨짐 방지)
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 모듈 임포트 (lib/ 하위)
sys.path.insert(0, str(Path(__file__).parent))

from lib import govt_sources
from lib import govt_playwright
from lib import naver_mail_client
from lib import dedupe as dedupe_mod
from lib import reconciler
from lib import scorer

import telegram_client

KST = timezone(timedelta(hours=9))
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def _setup_logging():
    today = datetime.now(KST).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"govt_radar_{today}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("govt_radar")


def collect_layer1(log):
    """1차 - 15개 공식 포털 크롤링"""
    log.info("Layer 1 시작: 1차 크롤링 (15개 포털)")
    items, stats = govt_sources.fetch_all(verbose=False)
    log.info(f"Layer 1 완료: {len(items)}건 (소스별: {stats})")
    return items, stats


def collect_layer1_playwright(log):
    """1차 (PW) - 화면 직접 렌더링으로 API/requests 누락 공고 추가 수집.

    silent failure 해소 핵심: API 잘 잡힘에도 사이트 화면엔 더 있을 수 있다는
    의심을 데이터로 검증. 결과는 reconciler가 items_l1과 매칭·합치기.
    """
    log.info("Layer 1 (PW) 시작: Playwright 7개 사이트 화면 추출")
    items, stats = govt_playwright.fetch_all_playwright(verbose=False)
    log.info(f"Layer 1 (PW) 완료: {len(items)}건 (소스별: {stats})")
    return items, stats


def collect_layer2(log, days_back=2):
    """2차 - 네이버 메일 스캔.

    Returns:
        (normalized_items, ok_flag) — Codex 2026-05-10: 사이트 다운을 "0건 수집"으로
        오해하지 않기 위해 정상/실패 플래그를 분리해 호출자에 전달한다.
    """
    log.info(f"Layer 2 시작: 네이버 메일 IMAP 스캔 (최근 {days_back}일)")
    try:
        items = naver_mail_client.scan_govt_announcements(days_back=days_back)
        # 메일 결과를 공통 스키마로 변환
        normalized = []
        for it in items:
            normalized.append({
                "source": f"메일({it['sender'][:30]})",
                "title": it["subject"],
                "url": (it["links"][0] if it["links"] else ""),
                "agency": _agency_from_sender(it["sender"]),
                "deadline": it.get("deadline"),
                "posted_date": it.get("received_at", "").split(" ")[0] if it.get("received_at") else None,
                "body_excerpt": it.get("body_excerpt", ""),
                "raw": {"mail_sender": it["sender"]},
            })
        log.info(f"Layer 2 완료: {len(normalized)}건")
        return normalized, True
    except Exception as e:
        log.error(f"Layer 2 실패: {e}")
        log.error(traceback.format_exc())
        return [], False


_SENDER_AGENCY_MAP = [
    # 기존 14개
    ("ypa.or.kr", "용인시산업진흥원"),
    ("gbsa.or.kr", "경기도경제과학진흥원"),
    ("gtek.or.kr", "경기테크노파크"),
    ("gtp.or.kr", "경기테크노파크"),
    ("at.or.kr", "농수산식품유통공사"),
    ("bizinfo.go.kr", "중소벤처기업부"),
    ("mss.go.kr", "중소벤처기업부"),
    ("kised.or.kr", "창업진흥원"),
    ("kotra.or.kr", "KOTRA"),
    ("mafra.go.kr", "농림축산식품부"),
    ("sbiz.or.kr", "소상공인시장진흥공단"),
    ("sbc.or.kr", "소상공인시장진흥공단"),
    ("nipa.kr", "정보통신산업진흥원"),
    ("smtech.go.kr", "중소기업기술정보진흥원"),
    ("gg.go.kr", "경기도"),
    # 2026-05-16 추가 — 1차 크롤러 사이트 차단 시 메일 IMAP 안전망 (codex fix D Stage 3)
    ("kosmes.or.kr", "중소벤처기업진흥공단"),
    ("smes.go.kr", "중소벤처기업부"),
    ("gcgf.or.kr", "경기신용보증재단"),
    ("kodma.or.kr", "중소기업유통센터"),
    ("fanfandaero.kr", "소상공인시장진흥공단"),
    ("gsp.or.kr", "경기스타트업플랫폼"),
    ("foodpolis.kr", "한국식품산업클러스터진흥원"),
    ("kfia.or.kr", "한국식품산업협회"),
    ("ksure.or.kr", "한국무역보험공사"),
    ("gbiz.go.kr", "중소벤처기업부"),
]


def _agency_from_sender(sender: str) -> str | None:
    """메일 발신자 주소에서 발주기관명 추정."""
    s = sender.lower()
    for domain, name in _SENDER_AGENCY_MAP:
        if domain in s:
            return name
    return None


def _clean_body(text, max_len=180):
    """본문 정제 — HTML 엔티티·점선·공백·연장 표기 제거, 길이 제한.

    - &nbsp; &amp; 같은 HTML 엔티티 디코드
    - 점선·말미·반복 기호 제거 (… ··· ☞ ※ ▶)
    - 연속 공백·줄바꿈 → 단일 공백
    - 길이 초과 시 단어 경계로 잘라 …
    """
    if not text:
        return ""
    import html as _html
    import re as _re

    # 1) HTML 엔티티 디코드
    cleaned = _html.unescape(text)
    # 2) 시각 장식 문자 제거 (의미 없는 점선·구분선)
    cleaned = _re.sub(r"[·•●○◎※▶▷☞◆◇■□★☆＊]+", " ", cleaned)
    # 3) 연속 ㅡ/ㅡ/-/_ 제거
    cleaned = _re.sub(r"[ㅡ\-_=]{3,}", " ", cleaned)
    # 4) zero-width / non-breaking space 제거
    cleaned = cleaned.replace("​", "").replace(" ", " ")
    # 5) 공백 정규화
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()

    if len(cleaned) <= max_len:
        return cleaned
    # 단어 경계로 자르기 (한글이라 공백 기준)
    truncated = cleaned[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len * 0.7:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def _clean_title(title, max_len=58):
    """제목 정제 — 의미 없는 꼬리 제거 + 길이 제한.

    제거 대상:
      - "참가기업 모집 공고", "신청 공고", "모집공고" 등 꼬리표
      - 연도 prefix("2026년 ") 단독은 유지
      - "(연장)", "(재공고)" 같은 부가 메모는 유지 (정보 가치 있음)
    """
    if not title:
        return ""
    import re as _re
    t = title.strip()
    # 의미 없는 꼬리 자동 절단 (정보 손실 없음)
    tail_patterns = [
        r"\s+참가기업\s*모집\s*공고\s*$",
        r"\s+참여기업\s*모집\s*공고\s*$",
        r"\s+신청\s*공고\s*$",
        r"\s+모집공고\s*$",
        r"\s+모집\s*공고\s*$",
        r"\s+공고\s*$",
    ]
    for p in tail_patterns:
        new_t = _re.sub(p, "", t)
        if new_t != t and len(new_t) >= 10:
            t = new_t
            break
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"
    return t


def _fmt_deadline(deadline_str, days_left):
    """마감 표기 — '~04/30 (수) · 2일 남음' 형식.

    Returns: (표시 문자열, 신호등 이모지)
        🔴: D-2 이하  🟠: D-7 이하  🟡: D-30 이하  🟢: 그 외
    """
    if not deadline_str:
        return "마감일 미정", "⚪"
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(deadline_str, "%Y-%m-%d")
        dow = ["월", "화", "수", "목", "금", "토", "일"][d.weekday()]
        date_str = f"~{d.month:02d}/{d.day:02d} ({dow})"
    except (ValueError, TypeError):
        return deadline_str, "⚪"

    if days_left is None:
        return date_str, "⚪"
    if days_left < 0:
        return f"{date_str} · 마감됨", "⚫"
    if days_left == 0:
        return f"{date_str} · 오늘 마감", "🔴"
    if days_left <= 2:
        return f"{date_str} · {days_left}일 남음", "🔴"
    if days_left <= 7:
        return f"{date_str} · {days_left}일 남음", "🟠"
    if days_left <= 30:
        return f"{date_str} · {days_left}일 남음", "🟡"
    return f"{date_str} · {days_left}일 남음", "🟢"


def _short_url(url):
    """URL 도메인 + 끝 식별자만 표시 (모바일 가독성)"""
    if not url:
        return ""
    import re as _re
    m = _re.match(r"https?://(?:www\.)?([^/]+)(/.+)?", url)
    if not m:
        return url[:60]
    domain = m.group(1)
    path = m.group(2) or ""
    # 끝 30자만
    if len(path) > 35:
        path = "/..." + path[-30:]
    return f"{domain}{path}"


def _format_announcement_block(s, include_body=False, number=None):
    """공고 한 건의 텔레그램 표시 블록 — 가독성 우선 (2026-04-28 v2).

    레이아웃:
        ━━━━━━━━━━━━━━━━━━━━
        🔴 #S1 · D-2 마감 임박
        제목 (꼬리표 제거됨)

        📅 ~04/30 (수) · 2일 남음
        🏛 경기도 (전국대상 가능)
        🎯 적합도 10/10 · 본사지역
        🔑 K-Food, 농식품, 수출

        📝 본문 (HTML 정리, 줄바꿈)

        🔗 도메인/식별자

    Args:
        s: scored item
        include_body: 본문·매칭키워드 포함 (S/A에만 True)
        number: 카테고리 내 순서 (예: "S1")
    """
    lines = []

    # 1) 헤더 — 신호등 + 번호 + 마감 요약
    deadline_str = s.get("deadline")
    days_left = s.get("deadline_days")
    deadline_label, signal = _fmt_deadline(deadline_str, days_left)

    header_parts = []
    if number:
        header_parts.append(f"{signal} #{number}")
    else:
        header_parts.append(signal)

    # 마감 임박 강조 라벨
    if days_left is not None and days_left >= 0:
        if days_left <= 2:
            header_parts.append(f"D-{days_left} 마감 임박")
        elif days_left <= 7:
            header_parts.append(f"D-{days_left} 임박")

    lines.append(" · ".join(header_parts))

    # 2) 제목 (정리됨)
    title = _clean_title(s.get("title", ""))
    lines.append(title)
    lines.append("")  # 빈 줄

    # 3) 핵심 메타데이터 (4줄 고정 패턴)
    lines.append(f"📅 {deadline_label}")
    if s.get("agency"):
        agency = s["agency"][:40]
        lines.append(f"🏛 {agency}")

    region_label = s.get("region_label", "?")
    score = s.get("score", 0)
    lines.append(f"🎯 적합도 {score}/10 · {region_label}")

    if include_body:
        # 매칭 키워드
        matched = s.get("matched", []) or []
        if matched:
            kw = ", ".join(matched[:5])
            lines.append(f"🔑 {kw}")

        # 자격요건
        raw = s.get("raw") or {}
        target = raw.get("trgetNm") or raw.get("biz_enyy")
        if target:
            t_clean = _clean_body(str(target), 70)
            if t_clean:
                lines.append(f"👥 {t_clean}")

        # 4) 본문
        body = s.get("body_excerpt") or ""
        if body:
            body_clean = _clean_body(body, 180)
            if body_clean:
                lines.append("")
                lines.append(f"📝 {body_clean}")

    # 5) URL (짧게)
    if s.get("url"):
        lines.append("")
        lines.append(f"🔗 {_short_url(s['url'])}")

    # 6) 명령 힌트 (S/A 등급에만, 사용자가 무엇을 할 수 있는지 알려줌)
    if include_body and number:
        lines.append("")
        lines.append(f"💬 /details {number}  /save {number}  /draft {number}")

    return "\n".join(lines)


def _assign_notify_ids(scored_items):
    """텔레그램 알림 노출 순서대로 notify_id 부여 (#S1, #A1, #B1...).

    /details, /why, /save, /draft 명령에서 매핑용. score+tier 동일 기준으로
    build_telegram_messages와 같은 순서를 따라야 일관성 보장.
    """
    EXCLUDE_TIER_PREFIX = (
        "타지역", "제외", "비공고", "메뉴", "자격미달", "검증불가",
    )
    notify = [
        s for s in scored_items
        if (s.get("score") or 0) >= 3
        and not (s.get("tier") or "").startswith(EXCLUDE_TIER_PREFIX)
    ]
    s_tier = [s for s in notify if s["score"] >= 9]
    a_tier = [s for s in notify if 7 <= s["score"] < 9]
    b_tier = [s for s in notify if 5 <= s["score"] < 7]
    # C 등급은 텔레그램에 카운트만 표시되므로 notify_id 부여 안 함

    for idx, s in enumerate(s_tier, 1):
        s["notify_id"] = f"S{idx}"
    for idx, s in enumerate(a_tier, 1):
        s["notify_id"] = f"A{idx}"
    for idx, s in enumerate(b_tier[:15], 1):  # B는 상위 15건만 노출
        s["notify_id"] = f"B{idx}"


def _build_govt_email_html(scored_items, today_str: str) -> str:
    """정부지원 레이더 일일 HTML 이메일 본문.

    S·A 등급: 개별 카드 (제목·기관·마감일·적합도 컬러바·키워드·URL)
    B 등급: 목록 테이블
    C 등급: 건수만
    """
    EXCLUDE_TIER_PREFIX = ("타지역", "제외", "비공고", "메뉴", "자격미달", "검증불가")
    notify = [
        s for s in scored_items
        if (s.get("score") or 0) >= 3
        and not (s.get("tier") or "").startswith(EXCLUDE_TIER_PREFIX)
    ]
    s_tier = [s for s in notify if s.get("score", 0) >= 9]
    a_tier = [s for s in notify if 7 <= s.get("score", 0) < 9]
    b_tier = [s for s in notify if 5 <= s.get("score", 0) < 7]
    c_count = sum(1 for s in notify if 3 <= s.get("score", 0) < 5)

    def _score_color(score):
        if score >= 9:
            return "#e74c3c"
        if score >= 7:
            return "#e67e22"
        if score >= 5:
            return "#f1c40f"
        return "#95a5a6"

    def _card(s, tier_label):
        score = s.get("score", 0)
        title = (s.get("title") or "제목 없음")[:60]
        agency = (s.get("agency") or "")[:40]
        deadline = s.get("deadline") or "마감일 미정"
        url = s.get("url") or ""
        matched = ", ".join((s.get("matched") or [])[:5])
        color = _score_color(score)
        score_bar = (
            f"<div style='background:#eee;border-radius:3px;height:6px;margin:6px 0;'>"
            f"<div style='background:{color};width:{min(score*10,100)}%;height:6px;border-radius:3px;'></div>"
            f"</div>"
        )
        url_html = (
            f"<a href='{url}' style='color:#3498db;font-size:12px;'>신청 페이지 열기</a>"
            if url else ""
        )
        kw_html = (
            f"<div style='font-size:11px;color:#7f8c8d;margin-top:4px;'>키워드: {matched}</div>"
            if matched else ""
        )
        return (
            f"<div style='border:1px solid #e1e4e8;border-left:4px solid {color};border-radius:6px;"
            f"padding:12px 14px;margin:8px 0;background:white;'>"
            f"<div style='font-size:13px;font-weight:bold;color:#2c3e50;'>{tier_label} {title}</div>"
            f"<div style='font-size:12px;color:#555;margin-top:3px;'>🏛 {agency} &nbsp;|&nbsp; 📅 {deadline}</div>"
            f"{score_bar}"
            f"<div style='font-size:12px;color:{color};font-weight:bold;'>적합도 {score}/10</div>"
            f"{kw_html}"
            f"<div style='margin-top:8px;'>{url_html}</div>"
            f"</div>"
        )

    cards_html = ""
    if s_tier:
        cards_html += f"<h2 style='color:#e74c3c;font-size:15px;margin:16px 0 4px 0;'>🚨 S 긴급 — 즉시 검토 ({len(s_tier)}건)</h2>"
        for i, s in enumerate(s_tier, 1):
            cards_html += _card(s, f"S{i}")

    if a_tier:
        cards_html += f"<h2 style='color:#e67e22;font-size:15px;margin:16px 0 4px 0;'>⭐ A 등급 — 사업계획서 후보 ({len(a_tier)}건)</h2>"
        for i, s in enumerate(a_tier, 1):
            cards_html += _card(s, f"A{i}")

    if b_tier:
        cards_html += f"<h2 style='color:#f39c12;font-size:15px;margin:16px 0 4px 0;'>📋 B 등급 — 검토 ({len(b_tier)}건)</h2>"
        rows = ""
        for i, s in enumerate(b_tier[:15], 1):
            title = (s.get("title") or "")[:55]
            deadline = s.get("deadline") or "미정"
            score = s.get("score", 0)
            rows += (
                f"<tr>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font-size:12px;color:#2c3e50;'>B{i}</td>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font-size:12px;'>{title}</td>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font-size:12px;text-align:center;'>{score}</td>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font-size:12px;color:#e74c3c;'>{deadline}</td>"
                f"</tr>"
            )
        cards_html += (
            "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            "<tr style='background:#f8f9fa;'>"
            "<th style='padding:5px 8px;text-align:left;'>ID</th>"
            "<th style='padding:5px 8px;text-align:left;'>공고명</th>"
            "<th style='padding:5px 8px;text-align:center;'>점수</th>"
            "<th style='padding:5px 8px;text-align:left;'>마감</th>"
            "</tr>"
            f"{rows}</table>"
        )

    if c_count:
        cards_html += (
            f"<p style='font-size:12px;color:#888;margin-top:12px;'>📎 C 등급 {c_count}건 — "
            "텔레그램 또는 Google Sheets에서 확인</p>"
        )

    if not cards_html:
        cards_html = "<p style='color:#888;'>오늘은 새로운 적합 공고가 없습니다.</p>"

    total = len(notify)
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#333;line-height:1.55;background:#fafbfc;'>
<div style='background:linear-gradient(135deg,#1a73e8 0%,#0d47a1 100%);color:white;padding:18px 22px;border-radius:8px;margin-bottom:20px;'>
  <h1 style='margin:0 0 4px 0;font-size:20px;'>🎯 정부지원 레이더</h1>
  <div style='opacity:0.9;font-size:13px;'>{today_str} 일일 요약 &nbsp;|&nbsp; 적합 공고 {total}건 (S {len(s_tier)} / A {len(a_tier)} / B {len(b_tier)} / C {c_count})</div>
</div>
<div style='background:#fff3cd;border-left:4px solid #f39c12;padding:10px 14px;border-radius:4px;margin-bottom:16px;font-size:13px;color:#856404;'>
  💬 텔레그램 명령: /details S1 &nbsp;·&nbsp; /why A2 &nbsp;·&nbsp; /save S1 &nbsp;·&nbsp; /draft A1
</div>
{cards_html}
<hr style='border:none;border-top:1px solid #eee;margin:24px 0;'>
<div style='font-size:11px;color:#aaa;text-align:center;'>자동 발송 · HeavyLover 정부지원 레이더 · 매일 09:00 KST</div>
</body></html>"""


def build_telegram_messages(scored_items, stats_l1, count_l2, today_str):
    """텔레그램 메시지 구성 (분할 발송용 list[str] 반환).

    텔레그램 4096자 제한 → 한 메시지가 3500자 넘으면 분할.
    S+A 등급: 본문 200자 + 자격·분야·매칭키워드 풀 표시
    B 등급: 제목+점수만
    C 등급: 카운트만
    """
    # 점수 ≥3 + tier가 진짜 적합한 것만 (강등된 자격미달·검증불가·비공고·메뉴 제외)
    EXCLUDE_TIER_PREFIX = (
        "타지역", "제외", "비공고", "메뉴", "자격미달", "검증불가",
    )
    notify = [
        s for s in scored_items
        if s["score"] >= 3
        and not (s.get("tier") or "").startswith(EXCLUDE_TIER_PREFIX)
    ]
    s_tier = [s for s in notify if s["score"] >= 9]
    a_tier = [s for s in notify if 7 <= s["score"] < 9]
    b_tier = [s for s in notify if 5 <= s["score"] < 7]
    c_tier = [s for s in notify if 3 <= s["score"] < 5]

    # 첫 메시지: 헤더
    DIVIDER = "━━━━━━━━━━━━━━━━━━━"
    messages = []
    current = []
    current.append(f"🎯 정부지원 레이더 · {today_str}")
    current.append(DIVIDER)
    l1_total = sum(v for v in stats_l1.values() if isinstance(v, int))
    current.append(f"📊 수집 {l1_total}건 (포털) + {count_l2}건 (메일)")
    current.append(
        f"✅ 적합 {len(notify)}건 · S {len(s_tier)} / A {len(a_tier)} / B {len(b_tier)} / C {len(c_tier)}"
    )
    current.append("")
    current.append("💡 사용법")
    current.append("  /details S1 — 풀 본문·자격·신청방법")
    current.append("  /why S1     — 적합 이유 분석")
    current.append("  /save A2    — 관심 공고 박제")
    current.append("  /draft S1   — 사업계획서 초안 생성")
    current.append("")

    def _start_section(emoji_label):
        """섹션 헤더 + 구분선"""
        current.append(DIVIDER)
        current.append(emoji_label)
        current.append(DIVIDER)
        current.append("")

    if s_tier:
        _start_section(f"🚨 S 긴급 — 즉시 검토 ({len(s_tier)}건)")
        for idx, s in enumerate(s_tier, 1):
            # notify_id는 _assign_notify_ids에서 미리 박제됨 (JSON 저장 호환)
            block = _format_announcement_block(s, include_body=True, number=f"S{idx}")
            # 현재 메시지 누적 길이 체크 (3500자 = 안전 한도)
            if sum(len(l) + 1 for l in current) + len(block) > 3500:
                messages.append("\n".join(current))
                current = [f"🚨 S 등급 (계속)", DIVIDER, ""]
            current.append(block)
            current.append("")  # 공고 간 빈 줄

    if a_tier:
        # A 등급 시작 전 분할
        if current and sum(len(l) + 1 for l in current) > 2500:
            messages.append("\n".join(current))
            current = []
        _start_section(f"⭐ A 사업계획서 후보 ({len(a_tier)}건)")
        for idx, s in enumerate(a_tier, 1):
            block = _format_announcement_block(s, include_body=True, number=f"A{idx}")
            if sum(len(l) + 1 for l in current) + len(block) > 3500:
                messages.append("\n".join(current))
                current = [f"⭐ A 등급 (계속)", DIVIDER, ""]
            current.append(block)
            current.append("")

    if b_tier:
        if current and sum(len(l) + 1 for l in current) > 2500:
            messages.append("\n".join(current))
            current = []
        _start_section(f"📋 B 검토 ({len(b_tier)}건, 상위 15건)")
        for idx, s in enumerate(b_tier[:15], 1):
            title = _clean_title(s.get("title", ""), max_len=52)
            d_label, signal = _fmt_deadline(s.get("deadline"), s.get("deadline_days"))
            current.append(f"{signal} #B{idx} [{s['score']}] {title}")
            current.append(f"   📅 {d_label}")
            if sum(len(l) + 1 for l in current) > 3500:
                messages.append("\n".join(current))
                current = ["📋 B 등급 (계속)", DIVIDER, ""]

    if c_tier:
        if current and sum(len(l) + 1 for l in current) > 3500:
            messages.append("\n".join(current))
            current = []
        current.append("")
        current.append(DIVIDER)
        current.append(f"📎 C 참고 — {len(c_tier)}건 (시트·다이제스트에서 확인)")

    if current:
        messages.append("\n".join(current))

    return messages


def build_telegram_message(scored_items, stats_l1, count_l2, today_str):
    """단일 메시지 (호환성 유지). 신규 코드는 build_telegram_messages 사용."""
    msgs = build_telegram_messages(scored_items, stats_l1, count_l2, today_str)
    return "\n\n".join(msgs)


# ─────────────────────────────────────────────────────────────────
# Codex review 2026-05-10 보강 — source health / Layer 4 fail-closed / seen-key dedup
# ─────────────────────────────────────────────────────────────────

SEEN_KEYS_PATH = Path(__file__).parent / "data" / "govt_radar" / "seen_keys.json"


def _build_source_health(stats_l1: dict, count_l2: int, layer2_ok: bool) -> dict:
    """소스별 수집 결과를 통합 health dict로 빌드.

    Args:
        stats_l1: govt_sources.fetch_all이 돌려준 dict[name, int|"ERROR: ..."]
        count_l2: Layer 2(네이버 메일) 수집 건수
        layer2_ok: Layer 2 정상 여부 (collect_layer2 예외 발생 시 False)

    Returns:
        {source_name: {"ok": bool, "count": int, "error": str|None}}
    """
    health = {}
    for name, val in (stats_l1 or {}).items():
        if isinstance(val, int):
            health[name] = {"ok": True, "count": val, "error": None}
        else:
            err = str(val).replace("ERROR: ", "", 1)
            health[name] = {"ok": False, "count": 0, "error": err}

    health["네이버메일(Layer2)"] = {
        "ok": layer2_ok,
        "count": count_l2 if layer2_ok else 0,
        "error": None if layer2_ok else "IMAP 스캔 실패",
    }
    return health


# ─────────────────────────────────────────────────────────────────
# 2026-05-16: silent failure 방지 — 일별 박제 + 누락 가능성 3종 신호
# failures.md (52)·codex adversarial 점검 fix A/B/F 반영
# ─────────────────────────────────────────────────────────────────

SOURCE_HEALTH_HISTORY_PATH = Path(__file__).parent / "data" / "govt_radar" / "source_health.json"
SOURCE_HEALTH_HISTORY_DAYS = 30
SOURCE_HEALTH_BOOTSTRAP_DAYS = 7  # 7일 미만 history면 drops·meta_drop 신호 비활성화


def _load_full_source_health_history() -> dict:
    """source_health.json 전체 로드. 손상·없음 시 빈 dict."""
    if not SOURCE_HEALTH_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(SOURCE_HEALTH_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _persist_source_health(source_health: dict, today_iso: str) -> None:
    """일별 소스 건수 박제. atomic write — 같은 cron 중복 실행에도 안전.
    30일 초과분 자동 정리."""
    SOURCE_HEALTH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = _load_full_source_health_history()
    today_record = {
        name: h.get("count", 0)
        for name, h in source_health.items()
        if h.get("ok")
    }
    history[today_iso] = today_record

    sorted_dates = sorted(history.keys(), reverse=True)
    if len(sorted_dates) > SOURCE_HEALTH_HISTORY_DAYS:
        for old_date in sorted_dates[SOURCE_HEALTH_HISTORY_DAYS:]:
            history.pop(old_date, None)

    tmp_path = SOURCE_HEALTH_HISTORY_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(SOURCE_HEALTH_HISTORY_PATH)


def _load_yesterday_health(today_iso: str) -> dict:
    """어제 박제값. 없으면 빈 dict — 부트스트랩 시 drops/meta_drop 자동 비활성화."""
    history = _load_full_source_health_history()
    today_dt = datetime.fromisoformat(today_iso).date()
    yesterday_iso = (today_dt - timedelta(days=1)).isoformat()
    return history.get(yesterday_iso, {})


def _load_7day_avg(today_iso: str) -> tuple[dict, int]:
    """최근 7일 이동평균 + 실제 박제된 일수. 부트스트랩 가드용."""
    history = _load_full_source_health_history()
    today_dt = datetime.fromisoformat(today_iso).date()
    recent_days = []
    for i in range(1, 8):
        d_iso = (today_dt - timedelta(days=i)).isoformat()
        if d_iso in history:
            recent_days.append(history[d_iso])
    if not recent_days:
        return {}, 0
    avg = {}
    all_sources = set()
    for day in recent_days:
        all_sources.update(day.keys())
    for src in all_sources:
        vals = [d.get(src, 0) for d in recent_days]
        avg[src] = sum(vals) / len(vals) if vals else 0
    return avg, len(recent_days)


def _diagnose_signals(source_health: dict, today_iso: str) -> dict:
    """누락 가능성 3종 신호 분류 (codex fix A·F 반영).

    Returns:
        {
          'new_zero': [...],         # 어제는 정상, 오늘 0건 — 즉시 알림 대상
          'persisting_zero': [...],  # 어제도 0/없음, 오늘도 0 — 3일 지속 시만 재알림
          'drops': [(name, y, t)],   # 어제 대비 70% 이상 급감 (y>=20 둔감화)
          'meta_drop': [(name, avg, t)],  # 기업마당·K-Startup 평소 평균 50% 이하
          'bootstrap': bool,         # history 7일 미만 → drops/meta_drop 비활성화 여부
          'history_days': int,
        }
    """
    yesterday = _load_yesterday_health(today_iso)
    weekly_avg, history_days = _load_7day_avg(today_iso)
    bootstrap = history_days < SOURCE_HEALTH_BOOTSTRAP_DAYS

    new_zero, persisting_zero, drops, meta_drops = [], [], [], []

    for name, h in source_health.items():
        if not h.get("ok"):
            continue
        today = h.get("count", 0)
        y_count = yesterday.get(name) if yesterday else None

        if today == 0:
            if y_count is None or y_count == 0:
                persisting_zero.append(name)
            else:
                new_zero.append(name)
            continue

        # drop 검사 — 부트스트랩 아닐 때만, y_count >= 20 둔감화 (codex fix A)
        if not bootstrap and y_count is not None and y_count >= 20:
            if today <= max(3, int(y_count * 0.3)):
                drops.append((name, y_count, today))

        # meta portal drop — 부트스트랩 아닐 때만
        if not bootstrap and name in ("기업마당", "K-Startup"):
            avg = weekly_avg.get(name, 0)
            if avg >= 50 and today < avg * 0.5:
                meta_drops.append((name, int(avg), today))

    return {
        "new_zero": new_zero,
        "persisting_zero": persisting_zero,
        "drops": drops,
        "meta_drop": meta_drops,
        "bootstrap": bootstrap,
        "history_days": history_days,
    }


def _check_outage(source_health: dict, today_iso: str, log) -> tuple[bool, dict]:
    """소스 다운 감지. codex fix A·F 반영 — 누락 가능성 3종 신호 기반.

    Trigger:
      - 성공률 < 75% (강화: 50→75)
      - 또는 새로 0건이 된 소스 3개 이상 (다발 silent failure)
      - 또는 어제 대비 70% 이상 급감 (셀렉터 부분 깨짐 초기 징후, y>=20 둔감화)
      - 또는 메타 포털 평소 평균 50% 이하 (가장 위험)
      - 또는 전체 0건 + 실패 1건 이상 (기존 유지)

    Returns: (outage, signals_dict)
    """
    if not source_health:
        return False, {}

    total = len(source_health)
    ok_count = sum(1 for h in source_health.values() if h["ok"])
    failed = [name for name, h in source_health.items() if not h["ok"]]
    total_items = sum(h["count"] for h in source_health.values())
    success_ratio = ok_count / total if total else 1.0

    signals = _diagnose_signals(source_health, today_iso)
    signals.update({
        "failed": failed,
        "success_ratio": success_ratio,
        "total_items": total_items,
        "ok_count": ok_count,
        "total": total,
    })

    # bootstrap(7일 미만)이면 new_zero만 체크 — 이력 없어 persisting인지 진짜 0건인지 모름
    # 정상 운영 시 new_zero+persisting_zero 합산 (codex fix A·F + 사후 재점검 🔴 수정)
    if signals["bootstrap"]:
        total_zero = len(signals["new_zero"])
    else:
        total_zero = len(signals["new_zero"]) + len(signals["persisting_zero"])
    outage = (
        success_ratio < 0.75
        or total_zero >= 3
        or len(signals["drops"]) >= 1
        or len(signals["meta_drop"]) >= 1
        or (total_items == 0 and failed)
    )

    log.info(
        "source health: %d/%d ok (%.0f%%) · 총 %d건 · 실패=%s · "
        "new_zero=%d · persisting_zero=%d · drops=%d · meta_drop=%d · bootstrap=%s(%d일)",
        ok_count, total, success_ratio * 100, total_items,
        failed or "-",
        len(signals["new_zero"]), len(signals["persisting_zero"]),
        len(signals["drops"]), len(signals["meta_drop"]),
        signals["bootstrap"], signals["history_days"],
    )
    return outage, signals


def _format_health_alert(signals: dict, today_iso: str) -> str:
    """헬스 알림 본문 — CLAUDE.md §ops알림언어 준수. 기술 용어 배제.
    codex fix B 반영 — [수집상태 점검 필요] 접두어로 공고 알림과 구분."""
    lines = ["[수집상태 점검 필요]"]
    lines.append(f"오늘({today_iso}) 정부지원 사이트 수집에 이상 신호가 잡혔습니다.")
    lines.append("")

    if signals.get("failed"):
        lines.append(f"■ 접속 실패한 사이트 ({len(signals['failed'])}곳)")
        lines.append(", ".join(signals["failed"][:15]))
        lines.append("")

    if signals.get("new_zero"):
        lines.append(f"■ 오늘 새로 한 건도 못 가져온 사이트 ({len(signals['new_zero'])}곳)")
        lines.append(", ".join(signals["new_zero"][:15]))
        lines.append("")

    if signals.get("persisting_zero"):
        lines.append(f"■ 계속 0건인 사이트 ({len(signals['persisting_zero'])}곳)")
        lines.append(", ".join(signals["persisting_zero"][:10]))
        lines.append("")

    if signals.get("drops"):
        lines.append(f"■ 어제 대비 크게 줄어든 사이트 ({len(signals['drops'])}곳)")
        for name, y, t in signals["drops"][:8]:
            lines.append(f"  · {name}: 어제 {y}건 → 오늘 {t}건")
        lines.append("")

    if signals.get("meta_drop"):
        lines.append(f"■ 메인 포털 급감 경고 ({len(signals['meta_drop'])}곳)")
        for name, avg, t in signals["meta_drop"]:
            lines.append(f"  · {name}: 평소 평균 {avg}건 → 오늘 {t}건 ← 가장 위험")
        lines.append("")

    if signals.get("bootstrap"):
        lines.append(
            f"※ 헬스체크 박제 {signals.get('history_days', 0)}일치만 누적("
            f"7일 미만)이라 어제 대비·평균 신호는 비활성. 7일 후 정상 동작."
        )
        lines.append("")

    lines.append("다음 단계: Claude에게 \"정부지원 자동화 점검해\" 요청")
    return "\n".join(lines)


def _send_alert(text: str, kind: str, log) -> bool:
    """알림 통합 발송 (codex fix B). kind에 따라 채널 분기.

    Args:
        kind: "health" → govt 채널 / "ops" → ops 채널 (백업·디버그용)
    """
    channel = "govt" if kind == "health" else "ops"
    try:
        ok = telegram_client.send_message(text[:4090], channel=channel)
        return bool(ok)
    except Exception as e:
        log.error(f"{channel} 알림 발송 실패: {e}")
        return False


def _send_ops_alert(text: str, log) -> bool:
    """ops 채널 알림 (기존 호출자 호환용 — Layer4 fail-closed 알림 등 유지)."""
    return _send_alert(text, kind="ops", log=log)


def _announcement_stable_key(item: dict) -> str:
    """공고 식별용 stable key (URL → announcement_id → title fallback)."""
    import hashlib as _h
    raw_meta = item.get("raw") or {}
    pid = raw_meta.get("pblancId") or raw_meta.get("pbancSn") or ""
    url = (item.get("url") or "").strip()
    title = (item.get("title") or "").strip()[:80]
    base = url or pid or title
    return _h.md5(base.encode("utf-8")).hexdigest()[:16]


def _content_hash(item: dict) -> str:
    """공고 본문 변경 감지용 해시 (제목+마감일+본문요약)."""
    import hashlib as _h
    title = (item.get("title") or "").strip()
    deadline = item.get("deadline") or ""
    body = (item.get("body_excerpt") or "")[:300]
    raw = f"{title}|{deadline}|{body}"
    return _h.md5(raw.encode("utf-8")).hexdigest()[:12]


def _load_seen_keys() -> dict:
    """seen_keys.json 로드. 스키마: {key: {"hash": str, "first_seen": "YYYY-MM-DD", "last_seen": "..."}}."""
    if not SEEN_KEYS_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_KEYS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # 파일 손상 시 초기화 (한 번 누적 잃지만 dedup만 잠시 약화)
        logging.getLogger("govt_radar").warning(
            f"seen_keys.json 손상 — 초기화: {e}"
        )
        return {}


def _save_seen_keys(seen: dict) -> None:
    """atomic write — tempfile + os.replace (도중 크래시 시 누적 손상 방지)."""
    SEEN_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_KEYS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SEEN_KEYS_PATH)


DEADLINE_RENOTIFY_WINDOWS = (2, 7)  # D-2, D-7 이하 진입 시 재알림 (content_hash 무관)


def _should_renotify_deadline(item: dict, prev: dict, today_iso: str) -> bool:
    """마감 임박 재알림 정책 (H-3 fix).

    같은 content_hash여도 마감일이 D-7 이하 또는 D-2 이하 윈도우에
    처음 진입한 날에는 재알림한다.

    last_seen == today면 이미 오늘 알림 → False.
    prev에 'deadline_notified' 필드로 이미 보낸 윈도우를 기록해 중복 차단.
    """
    if prev.get("last_seen") == today_iso:
        return False
    if not item.get("deadline"):
        return False
    try:
        from datetime import date as _date
        deadline = _date.fromisoformat(item["deadline"])
        today = _date.fromisoformat(today_iso)
        days_left = (deadline - today).days
    except (ValueError, TypeError):
        return False

    notified_windows = set(prev.get("deadline_notified") or [])
    for threshold in DEADLINE_RENOTIFY_WINDOWS:
        if 0 <= days_left <= threshold and threshold not in notified_windows:
            return True
    return False


def _classify_seen(items: list, seen: dict, today_iso: str) -> tuple[list, list]:
    """공고를 (신규, 갱신) 두 리스트로 분류. 기존(변경 없음)은 알림 제외.

    H-3 fix: content_hash 불변이라도 D-7/D-2 마감 임박 윈도우 첫 진입 시 재알림.

    Side effect: 각 item에 'seen_status' 필드 추가 ("new"|"updated"|"known"|"deadline_renotify").
    """
    new_items = []
    updated_items = []
    for it in items:
        key = _announcement_stable_key(it)
        h = _content_hash(it)
        prev = seen.get(key)
        if prev is None:
            it["seen_status"] = "new"
            new_items.append(it)
        elif prev.get("hash") != h:
            it["seen_status"] = "updated"
            updated_items.append(it)
        elif _should_renotify_deadline(it, prev, today_iso):
            it["seen_status"] = "deadline_renotify"
            updated_items.append(it)
        else:
            it["seen_status"] = "known"
        # in-memory 업데이트 (저장은 발송 성공 후)
        it["_seen_key"] = key
        it["_content_hash"] = h
    return new_items, updated_items


def _commit_seen_keys(items: list, seen: dict, today_iso: str) -> None:
    """발송 성공 후 seen 누적 갱신 + 디스크 atomic write.

    H-3 fix: deadline_renotify 발송 시 notified_windows에 해당 threshold 기록
    → 같은 윈도우에서 다음날 중복 재알림 차단.
    """
    from datetime import date as _date
    for it in items:
        key = it.get("_seen_key")
        h = it.get("_content_hash")
        if not key:
            continue
        if key in seen:
            seen[key]["last_seen"] = today_iso
            seen[key]["hash"] = h
        else:
            seen[key] = {"hash": h, "first_seen": today_iso, "last_seen": today_iso}
        # deadline_renotify 발송 시 어느 윈도우에서 보냈는지 기록
        if it.get("seen_status") == "deadline_renotify" and it.get("deadline"):
            try:
                deadline = _date.fromisoformat(it["deadline"])
                today = _date.fromisoformat(today_iso)
                days_left = (deadline - today).days
                notified = set(seen[key].get("deadline_notified") or [])
                for threshold in DEADLINE_RENOTIFY_WINDOWS:
                    if days_left <= threshold:
                        notified.add(threshold)
                seen[key]["deadline_notified"] = sorted(notified)
            except (ValueError, TypeError):
                pass
    _save_seen_keys(seen)


def _apply_layer4_fail_closed(scored: list, log, eligibility_attempted: bool = True, eligibility_failed: bool = False) -> tuple[int, str | None]:
    """Layer 4 실패 감지 → 해당 항목을 'eligibility_unverified' 티어로 다운그레이드.

    eligibility_checker.batch_check는 API 실패 시 예외 던지지 않고
    {"eligible": "unsure", "reason": "API 실패: ..."}로 inline 표시한다.
    여기서 그 결과를 재해석:
      - score≥5 + eligibility 미수행 또는 'API 실패'/'파싱 실패' reason → fail-closed 다운그레이드
      - eligibility 필드 자체가 없는 score≥5 항목도 fail-closed (H-4 fix: exception으로
        batch_check가 아예 실행 안 됐을 때 fail-open 방지)
      - 50% 이상이 'API 실패'면 시스템 전체 outage 간주 → ops 알림 메시지 반환

    Returns:
        (downgraded_count, ops_alert_message_or_None)
    """
    if not eligibility_attempted:
        return (0, None)
    # Defensive re-tier: if batch_check raised mid-execution, partial results
    # may have eligible="no" set but the tiering loop was skipped.
    if eligibility_failed:
        for s in scored:
            elig = s.get("eligibility") or {}
            tier = s.get("tier") or ""
            if elig.get("eligible") == "no" and not tier.startswith("자격미달"):
                s["tier"] = "자격미달 (LLM 판정, 재검증 누락)"
                s["tags"] = (s.get("tags") or []) + ["LLM_INELIGIBLE_DEFENSIVE"]
    api_failed = []
    high_score_total = 0
    for s in scored:
        if (s.get("score") or 0) < 5:
            continue
        # batch_check이 검증 대상에서 제외한 항목(타지역·제외)도 high_score_total에서 빼지 않음
        if (s.get("tier") or "").startswith(("타지역", "제외")):
            continue
        high_score_total += 1
        elig = s.get("eligibility")
        # H-4 fix: eligibility 필드 자체가 None이면 batch_check가 예외로 실행 안 된 것
        # → fail-open 허용 불가, api_failed에 포함시켜 다운그레이드
        if elig is None:
            api_failed.append(s)
            continue
        reason = elig.get("reason") or ""
        if "API 실패" in reason or "파싱 실패" in reason:
            api_failed.append(s)

    if not api_failed:
        return 0, None

    # 다운그레이드: 발송은 별도 그룹, 캘린더·다이제스트에서는 제외
    for s in api_failed:
        s["tier"] = "eligibility_unverified"
        s["tags"] = (s.get("tags") or []) + ["LLM_UNVERIFIED"]

    log.warning(
        f"Layer 4 fail-closed: {len(api_failed)}/{high_score_total}건 자격검증 미수행 (API 실패) → 다운그레이드"
    )

    # outage 임계치: 절반 이상 실패 또는 5건 이상 실패
    failure_ratio = len(api_failed) / max(high_score_total, 1)
    if failure_ratio >= 0.5 or len(api_failed) >= 5:
        # 가장 흔한 에러 메시지 추출
        sample_reason = (api_failed[0].get("eligibility") or {}).get("reason", "unknown")
        msg = (
            f"🚨 Anthropic API 실패 — Layer 4 자격검증 skip\n"
            f"실패: {len(api_failed)}/{high_score_total}건 (score≥5)\n"
            f"샘플: {sample_reason[:120]}\n"
            f"→ 해당 항목은 'eligibility_unverified' 티어로 발송됨 (수동 확인 필요)"
        )
        return len(api_failed), msg
    return len(api_failed), None


def _build_unverified_messages(scored: list, today_str: str) -> list[str]:
    """Layer 4 fail-closed 항목 별도 텔레그램 메시지 그룹."""
    unverified = [s for s in scored if (s.get("tier") or "") == "eligibility_unverified"]
    if not unverified:
        return []
    DIVIDER = "━━━━━━━━━━━━━━━━━━━"
    lines = [
        f"⚠️ 자격검증 미수행 — {len(unverified)}건 수동 확인 필요",
        f"({today_str} · Anthropic API 실패로 Layer 4 skip)",
        DIVIDER,
        "",
    ]
    for idx, s in enumerate(unverified, 1):
        title = _clean_title(s.get("title", ""), max_len=58)
        d_label, signal = _fmt_deadline(s.get("deadline"), s.get("deadline_days"))
        lines.append(f"{signal} #U{idx} [{s.get('score', 0)}] {title}")
        lines.append(f"   📅 {d_label}")
        if s.get("agency"):
            lines.append(f"   🏛 {s['agency'][:40]}")
        if s.get("url"):
            lines.append(f"   🔗 {_short_url(s['url'])}")
        lines.append("")
    msgs = []
    cur = []
    cur_len = 0
    for ln in lines:
        if cur_len + len(ln) + 1 > 3500:
            msgs.append("\n".join(cur))
            cur = ["⚠️ 자격검증 미수행 (계속)", DIVIDER, ""]
            cur_len = sum(len(l) + 1 for l in cur)
        cur.append(ln)
        cur_len += len(ln) + 1
    if cur:
        msgs.append("\n".join(cur))
    return msgs


def save_results(scored_items, today_str):
    """결과 JSON 저장 (시트 미연동 시 폴백)"""
    out_dir = Path(__file__).parent / "data" / "govt_radar"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"radar_{today_str}.json"

    serializable = []
    for s in scored_items:
        clean = {k: v for k, v in s.items() if k != "raw"}
        serializable.append(clean)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    return out_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 발송 없이 출력만")
    parser.add_argument("--days-back", type=int, default=2, help="메일 스캔 일수 (기본 2)")
    parser.add_argument("--skip-layer1", action="store_true", help="1차 크롤링 스킵 (메일만)")
    parser.add_argument("--skip-layer2", action="store_true", help="메일 스캔 스킵 (1차만)")
    parser.add_argument("--skip-eligibility", action="store_true", help="Layer 4 LLM 자격검증 스킵 (비용 절약)")
    args = parser.parse_args()

    log = _setup_logging()
    today_str = datetime.now(KST).strftime("%Y-%m-%d (%a)")

    log.info("=" * 60)
    log.info(f"정부지원 레이더 시작 - {today_str}")
    log.info("=" * 60)

    # Layer 1
    if args.skip_layer1:
        items_l1, stats_l1 = [], {}
        log.info("Layer 1 스킵")
    else:
        items_l1, stats_l1 = collect_layer1(log)

        # ─── Playwright primary 수집 + reconciliation ────────────────
        # 사용자 요구: "API로 받은 데이터에 누락이 있는지 모른다" → 화면 직접
        # 추출해서 cross-check. items_l1과 합치고 stats도 합쳐 source_health에 박제.
        try:
            items_pw, stats_pw = collect_layer1_playwright(log)
        except Exception as e:
            log.warning(f"Playwright 수집 실패 (전체 스킵): {type(e).__name__}: {e}")
            items_pw, stats_pw = [], {}

        if items_pw or stats_pw:
            rec = reconciler.reconcile(items_l1, items_pw)
            log.info(
                f"Reconciliation: API {rec['stats']['api_count']} · "
                f"PW {rec['stats']['pw_count']} · "
                f"matched {rec['stats']['matched_count']} · "
                f"playwright_only {rec['stats']['playwright_only_count']} "
                f"(API 누락 후보)"
            )
            items_l1 = rec["merged"]
            # 두 stats를 합쳐 source_health에 박제. 키는 (PW) 접미사로 분리됨.
            stats_l1 = {**stats_l1, **stats_pw}

            # API 누락 후보 → govt 채널 즉시 알림 (dry-run 제외)
            if rec["playwright_only"] and not args.dry_run:
                alert_text = reconciler.format_alert_text(
                    rec["playwright_only"], max_show=10
                )
                if alert_text:
                    try:
                        telegram_client.send_message(alert_text, channel="govt")
                        log.info(
                            f"API 누락 알림 발송: {rec['stats']['playwright_only_count']}건"
                        )
                    except Exception as e:
                        log.warning(f"API 누락 알림 발송 실패: {e}")

    # Layer 2
    if args.skip_layer2:
        items_l2 = []
        layer2_ok = True  # 의도적 skip은 outage 아님
        log.info("Layer 2 스킵")
    else:
        items_l2, layer2_ok = collect_layer2(log, days_back=args.days_back)

    # 2026-05-16: silent failure 방지 — 일별 박제 + 누락 가능성 3종 신호
    # codex adversarial 점검 fix A·B·F 반영
    today_iso = datetime.now(KST).strftime("%Y-%m-%d")
    source_health = _build_source_health(stats_l1, len(items_l2), layer2_ok)

    # 일별 박제 — dry-run에서도 누적해야 history 형성됨
    try:
        _persist_source_health(source_health, today_iso)
    except Exception as e:
        log.warning(f"source_health.json 박제 실패: {e}")

    outage_detected, signals = _check_outage(source_health, today_iso, log)
    if outage_detected and not args.dry_run:
        # govt 채널: 비전공자 친화 메시지 (CLAUDE.md §ops알림언어 준수)
        health_msg = _format_health_alert(signals, today_iso)
        _send_alert(health_msg, kind="health", log=log)
        # ops 채널: 디버깅용 간략 백업
        _send_alert(
            f"🚨 정부지원 레이더 — outage 감지\n"
            f"성공: {signals.get('ok_count')}/{signals.get('total')} "
            f"({signals.get('success_ratio', 0)*100:.0f}%) · "
            f"수집 {signals.get('total_items', 0)}건\n"
            f"실패 {len(signals.get('failed', []))} · "
            f"신규0건 {len(signals.get('new_zero', []))} · "
            f"급감 {len(signals.get('drops', []))} · "
            f"메타포털 {len(signals.get('meta_drop', []))}\n"
            f"실패 소스: {', '.join(signals.get('failed', [])[:8])}",
            kind="ops",
            log=log,
        )

    # 통합 + 중복 제거
    log.info("통합·중복제거 시작")
    all_items = items_l1 + items_l2
    deduped = dedupe_mod.dedupe(all_items, prefer_sources=["기업마당", "K-Startup", "창업진흥원"])
    log.info(f"통합 {len(all_items)}건 → 중복제거 후 {len(deduped)}건")

    # 적합도 점수
    log.info("적합도 점수 산출")
    scored = scorer.score_all(deduped)

    s_count = sum(1 for s in scored if s["score"] >= 9)
    a_count = sum(1 for s in scored if 7 <= s["score"] < 9)
    b_count = sum(1 for s in scored if 5 <= s["score"] < 7)
    c_count = sum(1 for s in scored if 3 <= s["score"] < 5)
    log.info(f"S {s_count} / A {a_count} / B {b_count} / C {c_count}")

    # Layer 4: 자격 검증 (적합도 ≥5만, ANTHROPIC_API_KEY 살아있을 때만)
    # 키워드로는 못 잡는 자격 미달(여성기업 한정·농민 한정·10년 이상 등) 필터
    from dotenv import load_dotenv as _ld
    _ld(override=True)
    eligibility_failed = False
    if not args.skip_eligibility and os.getenv("ANTHROPIC_API_KEY"):
        try:
            from lib import eligibility_checker
            scored = eligibility_checker.batch_check(scored, threshold_score=5.0, limit=80)
            # 자격 'no' 판정된 공고는 tier 강등 (캘린더·다이제스트에서 제외)
            no_count = sum(
                1 for s in scored
                if (s.get("eligibility") or {}).get("eligible") == "no"
            )
            unverifiable_count = 0
            for s in scored:
                e = (s.get("eligibility") or {}).get("eligible")
                body = s.get("body_excerpt") or ""
                if e == "no":
                    s["tier"] = "자격미달 (LLM 판정)"
                    s["tags"] = (s.get("tags") or []) + ["LLM_INELIGIBLE"]
                elif e == "unsure" and len(body.strip()) < 50 and not (s.get("source") or "").startswith("메일"):
                    # 본문 없어 LLM이 판단 못 한 항목 → 강등 (검증 불가)
                    # 단, 이메일 소스는 원문 링크 클릭 유도 — 강등 제외
                    s["tier"] = "검증불가 (본문 없음)"
                    s["tags"] = (s.get("tags") or []) + ["UNVERIFIABLE_NO_BODY"]
                    unverifiable_count += 1
            if no_count:
                log.info(f"자격 미달 강등: {no_count}건")
            if unverifiable_count:
                log.info(f"검증 불가 강등 (본문 없음): {unverifiable_count}건")
        except Exception as e:
            log.warning(f"자격검증 모듈 실패 (스킵): {type(e).__name__}: {e}")
            eligibility_failed = True
    else:
        if args.skip_eligibility:
            log.info("자격검증 스킵 (--skip-eligibility)")
        else:
            log.info("자격검증 스킵 (ANTHROPIC_API_KEY 없음)")

    # Codex 2026-05-10: Layer 4 fail-closed
    # batch_check이 API 실패를 "unsure"로 inline 변환하기 때문에 결과에서 재해석한다.
    # (eligibility_checker 모듈은 그대로 두고 govt_radar.py에서 후처리)
    eligibility_attempted = (not args.skip_eligibility and bool(os.getenv("ANTHROPIC_API_KEY")))
    downgraded_count, layer4_alert = _apply_layer4_fail_closed(scored, log, eligibility_attempted, eligibility_failed=eligibility_failed)
    if layer4_alert and not args.dry_run:
        _send_ops_alert(layer4_alert, log)

    # notify_id 부여 (텔레그램 명령 처리기에서 #S1·#A2 매핑용)
    # JSON 저장 전에 미리 박제해야 텔레그램 응답 시 동일 ID로 찾을 수 있음
    _assign_notify_ids(scored)

    # 결과 저장
    out_file = save_results(scored, datetime.now(KST).strftime("%Y%m%d"))
    log.info(f"결과 저장: {out_file}")

    # Codex 2026-05-10: seen-key dedup
    # 알림 후보(점수≥3 + 진짜 적합 tier)만 분류해서, 같은 공고 매일 중복 발송 방지.
    # 갱신(content_hash 변경)은 "🔄 갱신:" prefix 별도 그룹으로 발송.
    EXCLUDE_TIER_PREFIX = (
        "타지역", "제외", "비공고", "메뉴", "자격미달", "검증불가",
    )
    notify_candidates = [
        s for s in scored
        if (s.get("score") or 0) >= 3
        and not (s.get("tier") or "").startswith(EXCLUDE_TIER_PREFIX)
        and (s.get("tier") or "") != "eligibility_unverified"  # 별도 그룹으로 빼냄
    ]
    seen_keys = _load_seen_keys()
    today_iso = datetime.now(KST).strftime("%Y-%m-%d")
    new_items, updated_items = _classify_seen(notify_candidates, seen_keys, today_iso)
    known_count = sum(1 for it in notify_candidates if it.get("seen_status") == "known")
    log.info(
        f"seen-key dedup: 신규 {len(new_items)} · 갱신 {len(updated_items)} · 기존 {known_count}건 (알림 제외)"
    )
    # build_telegram_messages 입력은 "신규만". 기존 시그니처 보존.
    # (eligibility_unverified 항목도 빠지므로 messages는 "검증된 신규 공고"만 포함)
    new_keys_set = {it["_seen_key"] for it in new_items}
    new_scored_subset = [s for s in scored if s.get("_seen_key") in new_keys_set]
    messages = build_telegram_messages(new_scored_subset, stats_l1, len(items_l2), today_str)

    # 갱신 항목 별도 메시지 (간단 포맷)
    if updated_items:
        DIVIDER = "━━━━━━━━━━━━━━━━━━━"
        upd_lines = [
            f"🔄 갱신 공고 {len(updated_items)}건 — 마감일·본문 변경 감지",
            DIVIDER,
            "",
        ]
        for idx, it in enumerate(updated_items, 1):
            title = _clean_title(it.get("title", ""), max_len=58)
            d_label, signal = _fmt_deadline(it.get("deadline"), it.get("deadline_days"))
            upd_lines.append(f"🔄 #{idx} {signal} [{it.get('score', 0)}] {title}")
            upd_lines.append(f"   📅 {d_label}")
            if it.get("url"):
                upd_lines.append(f"   🔗 {_short_url(it['url'])}")
            upd_lines.append("")
        messages.append("\n".join(upd_lines))

    # 자격검증 미수행 항목 별도 그룹
    unverified_msgs = _build_unverified_messages(scored, today_str)
    messages.extend(unverified_msgs)

    # Codex review 2026-05-10: delivery contract 명시
    # 메시지가 있으면 텔레그램 또는 이메일 중 최소 1개 채널로 발송 성공해야 한다.
    # 둘 다 실패하면 main()이 nonzero 반환하여 GitHub Actions가 빨간불 표시.
    telegram_ok = True   # 메시지 없으면 vacuously true
    email_ok = True
    delivery_required = bool(messages)

    if args.dry_run:
        log.info(f"DRY-RUN - 텔레그램 {len(messages)}개 메시지 생략")
        print("\n" + "=" * 60)
        for i, m in enumerate(messages, 1):
            print(f"\n--- 메시지 {i}/{len(messages)} ({len(m)}자) ---")
            print(m)
        print("=" * 60)
    else:
        success_count = 0
        for i, m in enumerate(messages, 1):
            try:
                ok = telegram_client.send_message(m[:4090], channel="govt")
                if ok:
                    success_count += 1
                import time as _time
                _time.sleep(1)  # rate limit 회피
            except Exception as e:
                log.error(f"텔레그램 메시지 {i}/{len(messages)} 에러: {e}")
        log.info(f"텔레그램 발송: {success_count}/{len(messages)}개 성공")
        telegram_ok = (success_count == len(messages)) if delivery_required else True

        # 이메일 일일 요약 발송
        try:
            import email_sender
            today_str = datetime.now(KST).strftime("%Y-%m-%d")
            high_count = sum(1 for it in scored if it.get("score", 0) >= 7)
            subject = f"[정부지원 레이더] {today_str} 일일 요약 — 총 {len(scored)}건 / S·A {high_count}건"
            text_body = "\n\n".join(messages) if messages else "오늘 적합 공고 없음"
            html_body = _build_govt_email_html(scored, today_str)
            email_sender.send_email(subject=subject, text_body=text_body, html_body=html_body)
            log.info("이메일 일일 발송 성공")
            email_ok = True
        except Exception as e:
            log.error(f"이메일 발송 실패: {e}")
            email_ok = False

    # 캘린더 자동 등록 (적합도 ≥ 7 + 마감일 있는 공고)
    try:
        from lib import calendar_client
        calendar_results = calendar_client.sync_announcements(scored, log=log)
        log.info(f"캘린더 등록: {calendar_results}")
    except ImportError:
        log.info("캘린더 모듈 미설치 (정상)")
    except RuntimeError as e:
        log.warning(f"캘린더 스킵 (인증키 미설정): {e}")
    except Exception as e:
        log.error(f"캘린더 등록 에러: {e}")

    # Codex 2026-05-10: seen-key 갱신은 발송 성공 시에만 commit
    # (실패 시 다음 실행에서 재시도되어야 누락 방지)
    if not args.dry_run and (telegram_ok or email_ok):
        try:
            _commit_seen_keys(new_items + updated_items, seen_keys, today_iso)
            log.info(
                f"seen_keys.json 갱신: 신규 {len(new_items)}·갱신 {len(updated_items)} → 누적 {len(seen_keys)}키"
            )
        except OSError as e:
            log.error(f"seen_keys.json 저장 실패 (다음 실행에서 중복 알림 가능): {e}")

    log.info("정부지원 레이더 종료")

    # Delivery contract 검증
    if delivery_required and not (telegram_ok or email_ok):
        log.error(
            "🚨 delivery contract 위반 — 메시지 %d개 있으나 텔레그램·이메일 모두 발송 실패",
            len(messages),
        )
        return 2  # nonzero → GitHub Actions 빨간불
    if delivery_required and not telegram_ok:
        log.warning("텔레그램 일부 실패 — 이메일만 성공 (운영자 확인 필요)")
    # Codex 2026-05-10: source outage가 발생하면 delivery는 성공해도 nonzero 반환
    # (GitHub Actions 빨간불로 운영자 인지 강제)
    if outage_detected:
        log.error("Layer 1/2 outage 감지됨 — exit 3 반환 (delivery 성공 여부와 별개)")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
