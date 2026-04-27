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


def _fmt_score_breakdown(s):
    """점수 분해 표시: 적합도+지역+마감 = 총점"""
    fit = s.get("fit_score", 0)
    reg = s.get("region_score", 0)
    dl = s.get("deadline_score", 0)
    return f"적합 {fit} + 지역 {reg} + 마감 {dl} = {s['score']}"


def _clean_body(text, max_len=200):
    """본문 정제 - 공백·줄바꿈 정규화, 길이 제한"""
    if not text:
        return ""
    import re as _re
    cleaned = _re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rstrip() + "…"


def _format_announcement_block(s, include_body=False):
    """공고 한 건의 텔레그램 표시 블록 생성"""
    lines = []
    tag_str = " ".join(f"[{t}]" for t in s.get("tags", []))
    lines.append(f"• [{s['score']}] {s['title'][:70]} {tag_str}".strip())
    lines.append(f"  📊 {_fmt_score_breakdown(s)} ({s.get('region_label','?')})")

    # 마감일 + D-Day
    if s.get("deadline"):
        d_str = f"  📅 마감 {s['deadline']}"
        if s.get("deadline_days") is not None:
            d_str += f" (D{s['deadline_days']})"
        lines.append(d_str)

    # 발주기관
    if s.get("agency"):
        lines.append(f"  🏛 발주: {s['agency']}")

    if include_body:
        # 자격요건 (raw에서)
        raw = s.get("raw", {}) or {}
        target = raw.get("trgetNm") or raw.get("biz_enyy")
        if target:
            target_clean = _clean_body(str(target), 80)
            if target_clean:
                lines.append(f"  👥 대상: {target_clean}")

        # 분류·분야
        realm = raw.get("realm") or raw.get("supt_biz_clsfc")
        if realm:
            lines.append(f"  🏷 분야: {realm[:50]}")

        # 본문 200자
        body = s.get("body_excerpt") or ""
        if body:
            body_clean = _clean_body(body, 200)
            if body_clean:
                lines.append(f"  📝 {body_clean}")

        # 매칭 키워드 (사용자가 왜 적합한지 보여줌)
        matched = s.get("matched", [])
        if matched:
            m_str = ", ".join(matched[:5])
            lines.append(f"  🔑 매칭: {m_str}")

    # URL은 마지막
    if s.get("url"):
        lines.append(f"  🔗 {s['url'][:90]}")

    return "\n".join(lines)


def build_telegram_messages(scored_items, stats_l1, count_l2, today_str):
    """텔레그램 메시지 구성 (분할 발송용 list[str] 반환).

    텔레그램 4096자 제한 → 한 메시지가 3500자 넘으면 분할.
    S+A 등급: 본문 200자 + 자격·분야·매칭키워드 풀 표시
    B 등급: 제목+점수만
    C 등급: 카운트만
    """
    notify = [s for s in scored_items if s["score"] >= 3]
    s_tier = [s for s in notify if s["score"] >= 9]
    a_tier = [s for s in notify if 7 <= s["score"] < 9]
    b_tier = [s for s in notify if 5 <= s["score"] < 7]
    c_tier = [s for s in notify if 3 <= s["score"] < 5]

    # 첫 메시지: 헤더 + S 등급
    messages = []
    current = []
    current.append(f"🎯 정부지원 레이더 - {today_str}")
    current.append("")
    current.append(f"수집: 1차 {sum(v for v in stats_l1.values() if isinstance(v, int))}건 + 2차 {count_l2}건 (메일)")
    current.append(f"적합 후보: {len(notify)}건 (S {len(s_tier)} / A {len(a_tier)} / B {len(b_tier)} / C {len(c_tier)})")
    current.append("")

    if s_tier:
        current.append(f"🚨 S - 긴급 계획서 즉시 검토 ({len(s_tier)}건)")
        for s in s_tier:
            block = _format_announcement_block(s, include_body=True)
            # 현재 메시지 누적 길이 체크 (3500자 = 안전 한도)
            if sum(len(l) + 1 for l in current) + len(block) > 3500:
                messages.append("\n".join(current))
                current = [f"🚨 S 등급 (계속)"]
            current.append(block)
            current.append("")  # 공고 간 빈 줄

    if a_tier:
        # A 등급 시작 전 분할
        if current and sum(len(l) + 1 for l in current) > 2500:
            messages.append("\n".join(current))
            current = []
        current.append(f"⭐ A - 사업계획서 후보 ({len(a_tier)}건)")
        for s in a_tier:
            block = _format_announcement_block(s, include_body=True)
            if sum(len(l) + 1 for l in current) + len(block) > 3500:
                messages.append("\n".join(current))
                current = [f"⭐ A 등급 (계속)"]
            current.append(block)
            current.append("")

    if b_tier:
        if current and sum(len(l) + 1 for l in current) > 2500:
            messages.append("\n".join(current))
            current = []
        current.append(f"📋 B - 검토 ({len(b_tier)}건, 상위 15건)")
        for s in b_tier[:15]:
            current.append(f"• [{s['score']}] {s['title'][:60]} ({s.get('region_label','?')})")
            if sum(len(l) + 1 for l in current) > 3500:
                messages.append("\n".join(current))
                current = ["📋 B 등급 (계속)"]

    if c_tier:
        if current and sum(len(l) + 1 for l in current) > 3500:
            messages.append("\n".join(current))
            current = []
        current.append("")
        current.append(f"📎 C - 참고 {len(c_tier)}건 (시트에서 확인)")

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
