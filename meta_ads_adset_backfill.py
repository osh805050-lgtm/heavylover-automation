"""Meta 광고세트(adset) 단위 일별 시계열 백필.

기존 daily_campaign.csv와 같은 기간(2025-11-27 ~ 어제)을
adset 단위로 다시 수집해서 daily_adset.csv + Meta_Ads_Daily_AdSet 시트에 누적.

사용법:
    python meta_ads_adset_backfill.py                  # 전체 (2025-11-27부터)
    python meta_ads_adset_backfill.py --since 2026-04-01 --until 2026-04-30
    python meta_ads_adset_backfill.py --batch-days 7   # 7일씩 분할 호출 (rate limit 회피)

원칙:
- 같은 (date, adset_id) 키 재실행 시 덮어쓰기 (중복 누적 방지)
- 토큰 만료(401/OAuthException) 감지 시 텔레그램 ops 채널 알림
- USD → KRW 환산은 lib.meta_currency.CURRENCY_KRW_PER_USD (1450) 단일 출처
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta

import meta_ads_history
from meta_ads_client import fetch_adset_daily_range
from lib.meta_currency import CURRENCY_KRW_PER_USD
from meta_ads_weekly_report import summarize_row as summarize_campaign_row, _to_float


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2025-11-27", help="시작일 YYYY-MM-DD (기본 2025-11-27)")
    p.add_argument("--until", default=None, help="종료일 YYYY-MM-DD (기본 어제)")
    p.add_argument("--batch-days", type=int, default=14, help="한 번에 호출할 일수 (기본 14)")
    p.add_argument("--sleep", type=float, default=2.0, help="배치 간 sleep 초 (기본 2)")
    return p.parse_args()


def _adset_row_to_summary(target_date, r):
    """API row → adset_summaries 형식 변환 (KRW 환산 포함)."""
    m = summarize_campaign_row(r)
    # summarize_campaign_row가 2026-05-12부터 KRW 반환 — 재환산 금지
    cpc = None
    if m.get("spend") and m.get("clicks"):
        cpc = m["spend"] / m["clicks"]
    return {
        "date": target_date,
        "adset_id": r.get("adset_id"),
        "adset_name": r.get("adset_name") or "(이름 없음)",
        "campaign_id": r.get("campaign_id"),
        "campaign_name": r.get("campaign_name") or "(이름 없음)",
        "spend": m.get("spend"),
        "impressions": m.get("impressions"),
        "clicks": m.get("clicks"),
        "ctr_pct": m.get("ctr_pct"),
        "cpc_krw": cpc,
        "frequency": _to_float(r.get("frequency")),
        "purchases": m.get("purchases"),
        "purchase_value_krw": m.get("purchase_value"),
        "cpa_krw": m.get("cpa_krw"),
        "roas": m.get("roas"),
    }


def _notify_token_expired(err_str):
    try:
        from telegram_client import send_message
        send_message(
            f"⚠️ Meta adset 백필 중단 — 토큰 만료 의심\n"
            f"오류: {err_str[:200]}\n"
            f"확인: refresh_meta_token.py 또는 Graph API Explorer 재발급",
            channel="ops",
        )
    except Exception:
        pass


def main():
    args = parse_args()
    since = datetime.fromisoformat(args.since).date()
    until = (
        datetime.fromisoformat(args.until).date()
        if args.until
        else date.today() - timedelta(days=1)
    )
    if since > until:
        print(f"❌ since({since}) > until({until})")
        sys.exit(1)

    print(f"백필 범위: {since} ~ {until} (총 {(until - since).days + 1}일, 배치 {args.batch_days}일)")

    cur = since
    total_rows = 0
    batch_n = 0
    while cur <= until:
        batch_end = min(cur + timedelta(days=args.batch_days - 1), until)
        batch_n += 1
        print(f"\n[배치 {batch_n}] {cur} ~ {batch_end}")

        raw = fetch_adset_daily_range(cur.isoformat(), batch_end.isoformat())
        if not raw["ok"]:
            err = raw.get("error", "")
            print(f"  ❌ fetch 실패: {err[:300]}")
            if any(k in err for k in ["OAuthException", "Session has expired", "401", "code:190", "code:463"]):
                _notify_token_expired(err)
                sys.exit(2)
            time.sleep(args.sleep * 2)
            cur = batch_end + timedelta(days=1)
            continue

        # 일자별로 그룹핑 (Meta는 time_increment=1이라 row마다 date_start 다름)
        by_date = {}
        for r in raw.get("data", []):
            d = r.get("date_start")
            if not d:
                continue
            by_date.setdefault(d, []).append(r)

        all_summaries = []
        for d, rows in by_date.items():
            for r in rows:
                all_summaries.append(_adset_row_to_summary(d, r))

        if all_summaries:
            res = meta_ads_history.append_adset_range(all_summaries)
            print(f"  ✅ {len(all_summaries)}건 → CSV 누적 {res['adset_rows']}행 / {res['sheet']}")
            total_rows += len(all_summaries)
        else:
            print(f"  (광고세트 데이터 없음)")

        cur = batch_end + timedelta(days=1)
        if cur <= until:
            time.sleep(args.sleep)

    print(f"\n=== 완료: 총 {total_rows}건 누적, 배치 {batch_n}회 ===")


if __name__ == "__main__":
    main()
