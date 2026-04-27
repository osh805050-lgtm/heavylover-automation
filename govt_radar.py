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
from lib import naver_mail_client
from lib import dedupe as dedupe_mod
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


def collect_layer2(log, days_back=2):
    """2차 - 네이버 메일 스캔"""
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
                "agency": None,
                "deadline": it.get("deadline"),
                "posted_date": it.get("received_at", "").split(" ")[0] if it.get("received_at") else None,
                "body_excerpt": it.get("body_excerpt", ""),
                "raw": {"mail_sender": it["sender"]},
            })
        log.info(f"Layer 2 완료: {len(normalized)}건")
        return normalized
    except Exception as e:
        log.error(f"Layer 2 실패: {e}")
        log.error(traceback.format_exc())
        return []


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

    # Layer 2
    if args.skip_layer2:
        items_l2 = []
        log.info("Layer 2 스킵")
    else:
        items_l2 = collect_layer2(log, days_back=args.days_back)

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
                elif e == "unsure" and len(body.strip()) < 50:
                    # 본문 없어 LLM이 판단 못 한 항목 → 강등 (검증 불가)
                    s["tier"] = "검증불가 (본문 없음)"
                    s["tags"] = (s.get("tags") or []) + ["UNVERIFIABLE_NO_BODY"]
                    unverifiable_count += 1
            if no_count:
                log.info(f"자격 미달 강등: {no_count}건")
            if unverifiable_count:
                log.info(f"검증 불가 강등 (본문 없음): {unverifiable_count}건")
        except Exception as e:
            log.warning(f"자격검증 모듈 실패 (스킵): {type(e).__name__}: {e}")
    else:
        if args.skip_eligibility:
            log.info("자격검증 스킵 (--skip-eligibility)")
        else:
            log.info("자격검증 스킵 (ANTHROPIC_API_KEY 없음)")

    # notify_id 부여 (텔레그램 명령 처리기에서 #S1·#A2 매핑용)
    # JSON 저장 전에 미리 박제해야 텔레그램 응답 시 동일 ID로 찾을 수 있음
    _assign_notify_ids(scored)

    # 결과 저장
    out_file = save_results(scored, datetime.now(KST).strftime("%Y%m%d"))
    log.info(f"결과 저장: {out_file}")

    # 텔레그램 알림 (분할 발송)
    messages = build_telegram_messages(scored, stats_l1, len(items_l2), today_str)

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
                ok = telegram_client.send_message(m[:4090])
                if ok:
                    success_count += 1
                import time as _time
                _time.sleep(1)  # rate limit 회피
            except Exception as e:
                log.error(f"텔레그램 메시지 {i}/{len(messages)} 에러: {e}")
        log.info(f"텔레그램 발송: {success_count}/{len(messages)}개 성공")

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

    log.info("정부지원 레이더 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
