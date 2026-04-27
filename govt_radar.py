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


def build_telegram_message(scored_items, stats_l1, count_l2, today_str):
    """텔레그램 메시지 구성 - 적합도 ≥ 3만"""
    notify = [s for s in scored_items if s["score"] >= 3]
    s_tier = [s for s in notify if s["score"] >= 9]
    a_tier = [s for s in notify if 7 <= s["score"] < 9]
    b_tier = [s for s in notify if 5 <= s["score"] < 7]
    c_tier = [s for s in notify if 3 <= s["score"] < 5]

    lines = []
    lines.append(f"🎯 정부지원 레이더 - {today_str}")
    lines.append("")
    lines.append(f"수집: 1차 {sum(v for v in stats_l1.values() if isinstance(v, int))}건 (15개 포털) + 2차 {count_l2}건 (메일)")
    lines.append(f"적합 후보: {len(notify)}건 (S {len(s_tier)} / A {len(a_tier)} / B {len(b_tier)} / C {len(c_tier)})")
    lines.append("")

    if s_tier:
        lines.append("🚨 S - 긴급 (계획서 즉시 검토)")
        for s in s_tier[:5]:
            tag_str = " ".join(f"[{t}]" for t in s.get("tags", []))
            lines.append(f"  • [{s['score']}] {s['title'][:60]} {tag_str}")
            if s.get("deadline"):
                lines.append(f"    마감 {s['deadline']} (D{s.get('deadline_days', '?')})")
            if s.get("url"):
                lines.append(f"    {s['url'][:80]}")

    if a_tier:
        lines.append("")
        lines.append("⭐ A - 사업계획서 작성 후보")
        for s in a_tier[:8]:
            tag_str = " ".join(f"[{t}]" for t in s.get("tags", []))
            lines.append(f"  • [{s['score']}] {s['title'][:60]} {tag_str}")
            if s.get("deadline"):
                lines.append(f"    마감 {s['deadline']}")

    if b_tier:
        lines.append("")
        lines.append("📋 B - 검토 권장")
        for s in b_tier[:5]:
            lines.append(f"  • [{s['score']}] {s['title'][:60]}")

    if c_tier and len(c_tier) > 0:
        lines.append("")
        lines.append(f"📎 C - 참고 ({len(c_tier)}건, 상세는 시트)")

    return "\n".join(lines)


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

    # 텔레그램 알림
    msg = build_telegram_message(scored, stats_l1, len(items_l2), today_str)

    if args.dry_run:
        log.info("DRY-RUN - 텔레그램 발송 생략")
        print("\n" + "=" * 60)
        print(msg)
        print("=" * 60)
    else:
        try:
            ok = telegram_client.send_message(msg[:4000])  # 텔레그램 4096 제한
            log.info(f"텔레그램 발송: {'성공' if ok else '실패'}")
        except Exception as e:
            log.error(f"텔레그램 발송 에러: {e}")

    log.info("정부지원 레이더 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
