"""
meta_ads_weekly_report.py 단위 테스트

실행: python -m pytest tests/test_meta_ads_weekly_report.py -v
"""
import pytest
from unittest.mock import patch


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

KRW_PER_USD = 1450  # lib.meta_currency.CURRENCY_KRW_PER_USD와 동일


def _make_api_row(spend_usd, purchases, purchase_value_usd, clicks=100, impressions=10000):
    """Meta API raw row 샘플 생성 (USD 단위)"""
    cpa_usd = spend_usd / purchases if purchases else None
    roas = purchase_value_usd / spend_usd if spend_usd else None
    action_type = "omni_purchase"
    return {
        "campaign_id": "123",
        "campaign_name": "테스트 캠페인",
        "spend": str(spend_usd),
        "impressions": str(impressions),
        "clicks": str(clicks),
        "ctr": str(clicks / impressions * 100),
        "actions": [{"action_type": action_type, "value": str(purchases)}],
        "action_values": [{"action_type": action_type, "value": str(purchase_value_usd)}],
        "cost_per_action_type": [{"action_type": action_type, "value": str(cpa_usd)}] if cpa_usd else [],
        "purchase_roas": [{"action_type": action_type, "value": str(roas)}] if roas else [],
    }


# ── Case 1: summarize_row USD→KRW 환산 ──────────────────────────────────────

def test_summarize_row_converts_spend_to_krw():
    """spend는 USD→KRW (×1450), ROAS는 불변 (비율)."""
    from meta_ads_weekly_report import summarize_row

    row = _make_api_row(spend_usd=100.0, purchases=5, purchase_value_usd=358.0)
    result = summarize_row(row)

    assert result["spend"] == pytest.approx(100.0 * KRW_PER_USD, rel=1e-3), \
        f"spend는 USD×1450이어야 함. got {result['spend']}"
    assert result["purchase_value"] == pytest.approx(358.0 * KRW_PER_USD, rel=1e-3), \
        f"purchase_value는 USD×1450이어야 함. got {result['purchase_value']}"
    assert result["roas"] == pytest.approx(358.0 / 100.0, rel=1e-3), \
        f"ROAS는 비율이므로 환산 불필요. got {result['roas']}"


def test_summarize_row_cpa_in_krw():
    """CPA = spend(KRW) / purchases — KRW 단위 확인."""
    from meta_ads_weekly_report import summarize_row

    row = _make_api_row(spend_usd=200.0, purchases=4, purchase_value_usd=600.0)
    result = summarize_row(row)

    expected_cpa_krw = 200.0 * KRW_PER_USD / 4
    assert result["cpa_krw"] == pytest.approx(expected_cpa_krw, rel=1e-3), \
        f"CPA는 KRW 단위여야 함. got {result['cpa_krw']}"


# ── Case 2: aggregate_totals 이중 환산 없음 ──────────────────────────────────

def test_aggregate_totals_no_double_conversion():
    """aggregate_totals는 summarize_row 결과를 합산만. 이중 환산 없음."""
    from meta_ads_weekly_report import summarize_row, aggregate_totals

    rows_raw = [
        _make_api_row(spend_usd=100.0, purchases=3, purchase_value_usd=300.0),
        _make_api_row(spend_usd=50.0, purchases=2, purchase_value_usd=150.0),
    ]
    summarized = [summarize_row(r) for r in rows_raw]
    totals = aggregate_totals(summarized)

    expected_spend = (100.0 + 50.0) * KRW_PER_USD
    assert totals["spend"] == pytest.approx(expected_spend, rel=1e-3), \
        f"totals.spend 이중 환산 없어야 함. got {totals['spend']}, expected {expected_spend}"

    # CPA = total_spend(KRW) / total_purchases
    expected_cpa = expected_spend / 5
    assert totals["cpa_krw"] == pytest.approx(expected_cpa, rel=1e-3), \
        f"totals.cpa_krw 이중 환산 없어야 함. got {totals['cpa_krw']}"


# ── Case 3: build_comparison 대칭성 ─────────────────────────────────────────

def test_build_comparison_symmetric():
    """동일 USD raw 데이터 → current/previous 둘 다 환산됨 → 변동률 0%."""
    from meta_ads_weekly_report import summarize_row, build_comparison

    row = _make_api_row(spend_usd=100.0, purchases=5, purchase_value_usd=350.0)
    cur_rows = [summarize_row(row)]
    prev_rows = [summarize_row(row)]

    comparison = build_comparison(cur_rows, prev_rows)
    assert len(comparison) == 1

    changes = comparison[0]["changes"]
    for metric in ("spend", "cpa_krw", "roas"):
        ch = changes[metric]["change_pct"]
        assert ch == pytest.approx(0.0, abs=1e-6), \
            f"{metric} 변동률이 0이어야 함 (동일 데이터). got {ch}"


# ── Case 4: _build_weekly_flags 플래그 정확성 ────────────────────────────────

def test_build_weekly_flags_k1_trigger():
    """ROAS < 2.8 이면 K1 경보 플래그 생성."""
    from meta_ads_weekly_report import _build_weekly_flags

    totals = {"current": {"roas": 2.5, "cpa_krw": 18000}}
    flags = _build_weekly_flags(totals)
    assert any("K1" in f for f in flags), \
        f"ROAS 2.5 → K1 경보 플래그 있어야 함. flags={flags}"


def test_build_weekly_flags_no_false_alarm():
    """ROAS 3.5, CPA 정상 → 플래그 없음."""
    from meta_ads_weekly_report import _build_weekly_flags

    totals = {"current": {"roas": 3.5, "cpa_krw": 22000}}
    flags = _build_weekly_flags(totals)
    assert flags == [], f"정상 지표 → 플래그 없어야 함. got {flags}"
