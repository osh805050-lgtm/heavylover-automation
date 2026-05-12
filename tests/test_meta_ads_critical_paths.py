"""Meta 광고 자동화 핵심 경로 회귀 테스트.

실행: pip install -r requirements-dev.txt && pytest tests/ -v
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_extract_purchase_roas_prefers_offsite_pixel():
    """offsite_conversion.fb_pixel_purchase가 omni_purchase보다 우선."""
    os.environ.setdefault("META_AD_ACCOUNT_CURRENCY", "USD")
    from meta_ads_client import extract_purchase_roas

    row = {
        "purchase_roas": [
            {"action_type": "omni_purchase", "value": "5.0"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3.0"},
        ]
    }
    value, source = extract_purchase_roas(row)
    assert value == 3.0
    assert source == "offsite_conversion.fb_pixel_purchase"


def test_check_account_currency_raises_when_missing():
    """META_AD_ACCOUNT_CURRENCY 미설정 시 RuntimeError."""
    from lib.meta_currency import _check_account_currency
    import pytest

    saved = os.environ.pop("META_AD_ACCOUNT_CURRENCY", None)
    try:
        with pytest.raises(RuntimeError):
            _check_account_currency()
    finally:
        if saved is not None:
            os.environ["META_AD_ACCOUNT_CURRENCY"] = saved


def test_build_ad_top5_card_empty_returns_empty_string():
    """ads=[] 전달 시 빈 문자열 반환 (카드 미표시)."""
    os.environ.setdefault("META_AD_ACCOUNT_CURRENCY", "USD")
    from meta_ads_email_daily import _build_ad_top5_card

    result = _build_ad_top5_card([])
    assert result == ""


def test_ad_columns_matches_ad_headers():
    """meta_ads_history.AD_COLUMNS와 meta_ads_sheets_client.AD_HEADERS가 동일 (단일 출처)."""
    os.environ.setdefault("META_AD_ACCOUNT_CURRENCY", "USD")
    from meta_ads_history import AD_COLUMNS
    from meta_ads_sheets_client import AD_HEADERS

    assert AD_COLUMNS == list(AD_HEADERS), (
        "AD_COLUMNS vs AD_HEADERS 불일치 — meta_ads_history.py 또는 meta_ads_sheets_client.py 확인"
    )
