"""
Meta 광고 통화 환산 공용 유틸.

순환 import 차단용 분리 모듈:
  meta_ads_report.py      → from lib.meta_currency import ...
  meta_ads_weekly_report.py → from lib.meta_currency import ...

환율 고정 1,450원/USD (2026-04-28 승인). 변동 환율 미사용 — 추세 일관성 우선.
"""
import os

# 환율 상수 — 변경 시 이 파일 한 곳만 수정
CURRENCY_KRW_PER_USD = 1450
CURRENCY_FIELDS_USD = {"spend", "cpc_krw", "cpm_krw", "cpa_krw", "purchase_value_krw"}

_ACCOUNT_CURRENCY = os.getenv("META_AD_ACCOUNT_CURRENCY", "USD").upper()


def _check_account_currency():
    """통화 guard — run() 진입 시점에만 호출. import 시 raise 금지."""
    raw = os.getenv("META_AD_ACCOUNT_CURRENCY")
    if not raw:
        raise RuntimeError(
            "META_AD_ACCOUNT_CURRENCY 미설정: .env 또는 workflow env에 명시 필수. "
            "예: META_AD_ACCOUNT_CURRENCY=USD"
        )
    account_currency = raw.upper()
    if account_currency != "USD" and os.getenv("META_ALLOW_NON_USD") != "1":
        raise RuntimeError(
            f"⚠️ Meta 광고 계정 통화가 {account_currency} (USD 아님). "
            f"이 상태로 _to_krw 호출하면 모든 금액 ×{CURRENCY_KRW_PER_USD} 사고 발생. "
            "META_ALLOW_NON_USD=1 환경변수 설정 시만 진행 (단, _to_krw 로직 검토 필수)."
        )


def _to_krw(value, currency_unit="USD"):
    """USD → KRW 환산. None은 None. 이미 KRW면 그대로.
    USD/KRW 외 통화는 RuntimeError — silent ×1450 사고 방지.
    """
    if value is None:
        return None
    unit = (currency_unit or "USD").upper()
    if unit == "KRW":
        return value
    if unit != "USD":
        raise RuntimeError(
            f"⚠️ _to_krw: 지원하지 않는 통화 '{unit}'. "
            f"USD 환율({CURRENCY_KRW_PER_USD})로 silent 변환하면 사고 발생. "
            "lib/meta_currency.py 환율 추가 필요."
        )
    try:
        return float(value) * CURRENCY_KRW_PER_USD
    except (TypeError, ValueError):
        return None


def convert_metrics_to_krw(m):
    """compute_metrics 결과 dict를 KRW 단위로 환산. 비율 지표(CTR·ROAS·Frequency)는 그대로.
    META_AD_ACCOUNT_CURRENCY=KRW 설정 시 ×1450 생략 (API가 이미 KRW 반환).
    """
    _check_account_currency()
    account_currency = os.getenv("META_AD_ACCOUNT_CURRENCY", "USD").upper()
    out = dict(m)
    for k in ("spend", "cpc_krw", "cpm_krw", "cpa_krw", "purchase_value_krw"):
        if out.get(k) is not None:
            out[k] = _to_krw(out[k], currency_unit=account_currency)
    return out


def _compare(actual, benchmark, higher_better=True):
    """벤치마크 대비 비율 문자열 (우수/평균/미달)"""
    if actual is None or benchmark is None or benchmark == 0:
        return "비교 불가"
    ratio = actual / benchmark
    if higher_better:
        if ratio >= 1.5:
            verdict = "우수"
        elif ratio >= 1.0:
            verdict = "평균 이상"
        elif ratio >= 0.7:
            verdict = "평균 미달"
        else:
            verdict = "크게 미달"
    else:
        if ratio <= 0.7:
            verdict = "우수"
        elif ratio <= 1.0:
            verdict = "평균 이내"
        elif ratio <= 1.5:
            verdict = "평균 초과"
        else:
            verdict = "크게 초과"
    return f"{ratio*100:.0f}% ({verdict})"
