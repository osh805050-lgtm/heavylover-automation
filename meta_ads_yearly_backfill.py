"""1년치 Meta 광고 데이터 백필 — daily.csv + daily_campaign.csv 일괄 채움.

사용:
    python meta_ads_yearly_backfill.py            # 직전 365일
    python meta_ads_yearly_backfill.py --days 730 # 직전 730일

원칙 (CLAUDE.md §0):
- 같은 (date, campaign_id) 키 재실행 시 덮어쓰기 (upsert)
- USD → KRW 환산 (1,450원/USD 고정)
- 기존 1일치 자동화와 충돌 없음 — 같은 CSV에 누적
"""
import argparse
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from meta_ads_client import (
    fetch_account_daily_range,
    fetch_campaign_daily_range,
    extract_action,
    extract_action_value,
    extract_cost_per_action,
    extract_purchase_roas,
)
import meta_ads_history
from meta_ads_report import compute_metrics
from lib.meta_currency import CURRENCY_KRW_PER_USD

KST = timezone(timedelta(hours=9))


def _to_krw_metrics(m):
    out = dict(m)
    for k in ("spend", "cpc_krw", "cpm_krw", "cpa_krw", "purchase_value_krw"):
        if out.get(k) is not None:
            out[k] = float(out[k]) * CURRENCY_KRW_PER_USD
    return out


def _campaign_summary_to_krw(c):
    """캠페인 row를 history append용 dict로 변환 + USD→KRW."""
    PURCHASE_TYPES = ["omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"]

    def _f(key):
        v = c.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    purchases = next((extract_action(c, t) for t in PURCHASE_TYPES if extract_action(c, t) is not None), None)
    purchase_value = next((extract_action_value(c, t) for t in PURCHASE_TYPES if extract_action_value(c, t) is not None), None)
    cpa = next((extract_cost_per_action(c, t) for t in PURCHASE_TYPES if extract_cost_per_action(c, t) is not None), None)
    roas = extract_purchase_roas(c)

    spend = _f("spend")
    if cpa is None and purchases and purchases > 0 and spend:
        cpa = spend / purchases
    if roas is None and purchase_value and spend:
        roas = purchase_value / spend if spend > 0 else None

    return {
        "campaign_id": c.get("campaign_id"),
        "campaign_name": c.get("campaign_name") or "",
        "spend": (spend or 0) * CURRENCY_KRW_PER_USD if spend else None,
        "impressions": _f("impressions"),
        "clicks": _f("clicks"),
        "ctr_pct": _f("ctr"),
        "purchases": purchases,
        "purchase_value": (purchase_value or 0) * CURRENCY_KRW_PER_USD if purchase_value else None,
        "cpa_krw": (cpa or 0) * CURRENCY_KRW_PER_USD if cpa else None,
        "roas": roas,
    }


def backfill(days=365):
    today = datetime.now(KST).date()
    since = (today - timedelta(days=days)).isoformat()
    until = (today - timedelta(days=1)).isoformat()  # 어제까지
    print(f"백필 범위: {since} ~ {until} ({days}일)")

    # 1. 계정 합계 일별
    print("\n[1/2] 계정 합계 일별 fetch...")
    acc_raw = fetch_account_daily_range(since, until)
    if not acc_raw["ok"]:
        print(f"FAIL: {acc_raw['error']}")
        return 1
    print(f"계정 합계 {len(acc_raw['data'])}일 받음")

    # 2. 캠페인 일별
    print("\n[2/2] 캠페인별 일별 fetch (시간 걸릴 수 있음)...")
    camp_raw = fetch_campaign_daily_range(since, until)
    if not camp_raw["ok"]:
        print(f"WARN: {camp_raw['error']} — 받은 만큼만 누적")
    print(f"캠페인 행 {len(camp_raw['data'])}건 받음")

    # 3. 일자별 그룹화
    by_date_account = {}
    for row in acc_raw["data"]:
        d = row.get("date_start")
        if d:
            by_date_account[d] = row

    by_date_campaigns = {}
    for row in camp_raw["data"]:
        d = row.get("date_start")
        if not d:
            continue
        by_date_campaigns.setdefault(d, []).append(row)

    # 4. 일자별로 history.append_daily 호출 (CSV+Sheets 통합)
    print(f"\n누적 처리: {len(by_date_account)}일")
    pushed = 0
    sheet_skipped = False
    for d in sorted(by_date_account.keys()):
        acc_row = by_date_account[d]
        metrics_usd = compute_metrics(acc_row)
        metrics = _to_krw_metrics(metrics_usd)

        camp_rows = by_date_campaigns.get(d, [])
        camp_summaries = [_campaign_summary_to_krw(c) for c in camp_rows]

        # raw 형태로 감싸기
        fake_raw = {"ok": True, "data": [acc_row], "target_date": d, "error": None}
        try:
            res = meta_ads_history.append_daily(d, fake_raw, metrics, camp_summaries)
            pushed += 1
            sheet_msg = res["sheet"].get("daily", "")
            if "skip" in sheet_msg and not sheet_skipped:
                print(f"  (시트 push skip — CSV만 누적: {sheet_msg})")
                sheet_skipped = True
            if pushed % 30 == 0:
                print(f"  진행: {pushed}/{len(by_date_account)}일 ({d})")
        except Exception as e:
            print(f"  {d} 실패: {e}")

    print(f"\n백필 완료: {pushed}/{len(by_date_account)}일 + 캠페인 {len(camp_raw['data'])}건")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    sys.exit(backfill(days=args.days))
