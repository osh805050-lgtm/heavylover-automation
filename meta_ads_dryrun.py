"""
Meta 광고 자동화 드라이런 — Meta 토큰 없이 더미 데이터로 풀 파이프라인 검증

목적:
- META_ACCESS_TOKEN 발급 전에도 다음 검증 가능:
    1. Anthropic API 호출 (Claude 짧은/심층 코멘트 생성)
    2. 텔레그램 메시지 전송
    3. 이메일 HTML 심층 리포트 전송
    4. Google Sheets push (재구매용 SA 키 자동 폴백)
    5. CSV 시계열 누적 (data/meta_ads/daily.csv)

- 더미 데이터: 헤비로버 베이스라인 근방 (ROAS 3.4, CPA 28000, CTR 1.5%)
- 실행 후 실제 토큰만 발급되면 meta_ads_report.py가 그대로 돌아감

사용:
    python meta_ads_dryrun.py
"""

import io
import json
import os
import sys
from datetime import date, timedelta, timezone, datetime
from pathlib import Path

# Windows cp949 콘솔 대비
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

KST = timezone(timedelta(hours=9))


def make_dummy_account_response(target_date):
    """Meta Insights API 응답 형태 그대로 모사. 실제 응답 구조 유지."""
    return {
        "ok": True,
        "target_date": target_date,
        "data": [{
            "spend": "152340",
            "impressions": "23150",
            "clicks": "347",
            "ctr": "1.498",
            "cpc": "439",
            "cpm": "6580",
            "frequency": "2.31",
            "reach": "10020",
            "actions": [
                {"action_type": "purchase", "value": "5"},
                {"action_type": "add_to_cart", "value": "12"},
                {"action_type": "page_view", "value": "298"},
            ],
            "action_values": [
                {"action_type": "purchase", "value": "518000"},
            ],
            "cost_per_action_type": [
                {"action_type": "purchase", "value": "30468"},
            ],
            "purchase_roas": [
                {"action_type": "omni_purchase", "value": "3.40"},
            ],
            "date_start": target_date,
            "date_stop": target_date,
        }],
        "error": None,
    }


def make_dummy_campaigns(target_date):
    """캠페인별 더미 데이터 — 위너/패배자 섞어서 분석 다양성 확인"""
    base = [
        {
            "campaign_id": "120201234567890001",
            "campaign_name": "벌크업_30대남_단백질40g_훈제닭다리_v3",
            "spend": "62500", "impressions": "9800", "clicks": "165",
            "ctr": "1.683", "actions": [{"action_type": "purchase", "value": "3"}],
            "action_values": [{"action_type": "purchase", "value": "310000"}],
            "cost_per_action_type": [{"action_type": "purchase", "value": "20833"}],
            "purchase_roas": [{"action_type": "omni_purchase", "value": "4.96"}],
        },
        {
            "campaign_id": "120201234567890002",
            "campaign_name": "다이어트_20대여_저당시리얼_v1",
            "spend": "48200", "impressions": "8400", "clicks": "98",
            "ctr": "1.167", "actions": [{"action_type": "purchase", "value": "1"}],
            "action_values": [{"action_type": "purchase", "value": "58000"}],
            "cost_per_action_type": [{"action_type": "purchase", "value": "48200"}],
            "purchase_roas": [{"action_type": "omni_purchase", "value": "1.20"}],
        },
        {
            "campaign_id": "120201234567890003",
            "campaign_name": "직장인_고단백냉동도시락_800kcal_v2",
            "spend": "41640", "impressions": "4950", "clicks": "84",
            "ctr": "1.697", "actions": [{"action_type": "purchase", "value": "1"}],
            "action_values": [{"action_type": "purchase", "value": "150000"}],
            "cost_per_action_type": [{"action_type": "purchase", "value": "41640"}],
            "purchase_roas": [{"action_type": "omni_purchase", "value": "3.60"}],
        },
    ]
    return {"ok": True, "data": base, "since": target_date, "until": target_date, "error": None}


def main():
    # 통화 가드: META_AD_ACCOUNT_CURRENCY를 run() 진입 전에 설정해야 함.
    # _check_account_currency()는 런타임 os.getenv 재호출이라 현재 순서 OK.
    # 더미값이 이미 KRW 단위이므로 패스스루(_to_krw ×1 처리)로 설정.
    os.environ["META_AD_ACCOUNT_CURRENCY"] = "KRW"
    os.environ["META_ALLOW_NON_USD"] = "1"
    print("=" * 60)
    print("Meta 광고 자동화 드라이런 시작 (더미 데이터)")
    print("=" * 60)

    # 어제 날짜 (실제 운영과 동일하게)
    target_date = (datetime.now(KST).date() - timedelta(days=1)).isoformat()
    print(f"대상 일자: {target_date}\n")

    # === 1. Meta Client 패치 ===
    import meta_ads_client
    original_account = meta_ads_client.fetch_account_insights
    original_campaign = meta_ads_client.fetch_campaign_insights
    original_adset = meta_ads_client.fetch_adset_daily_range
    original_ad = meta_ads_client.fetch_ad_daily_range
    original_creatives = meta_ads_client.fetch_ad_creatives

    meta_ads_client.fetch_account_insights = lambda target_date=None, **k: make_dummy_account_response(
        target_date or (datetime.now(KST).date() - timedelta(days=1)).isoformat()
    )
    meta_ads_client.fetch_campaign_insights = lambda since, until, **k: make_dummy_campaigns(since)
    meta_ads_client.fetch_adset_daily_range = lambda since, until, **k: {"ok": True, "data": [], "error": None}
    meta_ads_client.fetch_ad_daily_range = lambda since, until, **k: {"ok": True, "data": [], "error": None}
    meta_ads_client.fetch_ad_creatives = lambda ad_ids, **k: {}
    # validate_insights도 ok 처리
    meta_ads_client.validate_insights = lambda raw: {"valid": True, "issues": []}

    # report.py가 patched 함수를 직접 import 해뒀으므로 그쪽도 교체
    import meta_ads_report
    meta_ads_report.fetch_account_insights = meta_ads_client.fetch_account_insights
    meta_ads_report.fetch_campaign_insights = meta_ads_client.fetch_campaign_insights
    meta_ads_report.fetch_adset_daily_range = meta_ads_client.fetch_adset_daily_range
    meta_ads_report.validate_insights = meta_ads_client.validate_insights

    # === 2. report.run() 호출 ===
    print("[1/1] meta_ads_report.run() 실행")
    print("-" * 60)
    try:
        ret = meta_ads_report.run()
        print("-" * 60)
        print(f"run() 종료 코드: {ret}")
    except Exception as e:
        print(f"실행 중 예외: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # 복원
        meta_ads_client.fetch_account_insights = original_account
        meta_ads_client.fetch_campaign_insights = original_campaign
        meta_ads_client.fetch_adset_daily_range = original_adset
        meta_ads_client.fetch_ad_daily_range = original_ad
        meta_ads_client.fetch_ad_creatives = original_creatives

    print()
    print("=" * 60)
    print("드라이런 완료 — 다음을 확인하세요:")
    print("  1. 텔레그램에 [Meta 광고] 메시지 도착했는지")
    print("  2. 이메일에 [Meta 광고 일일 심층 리포트] 도착했는지")
    print("  3. Google Sheets 'Meta_Ads_Daily' 시트에 행 추가됐는지")
    print(f"  4. data/meta_ads/daily.csv에 {target_date} 행 추가됐는지")
    print(f"  5. docs/meta-ads/reports/{target_date}.md 파일 존재하는지")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
