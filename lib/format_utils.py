"""숫자 포맷 표준 — 모든 리포트에서 공용으로 import.

정책:
- 금액: 소수점 없음, 천단위 콤마, 원 단위 표기  예) 12,340,000원
- 비율/ROAS: 소수점 둘째 자리  예) 3.51 / 12.84%
- 변화율: 소수점 둘째 자리 + 부호 강제  예) +12.34% / -32.50%
- 건수: 소수점 없음, 천단위 콤마  예) 732건
- 일수: 소수점 없음  예) 10일
"""
from __future__ import annotations


def fmt_money(v, short: bool = False) -> str:
    """금액(원). short=True이면 1억 이상은 '1.23억원', 1만 이상은 '1,234만원'."""
    if v is None:
        return "—"
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    if short:
        if abs(n) >= 100_000_000:
            return f"{n / 100_000_000:.2f}억원"
        if abs(n) >= 10_000:
            return f"{n / 10_000:,.0f}만원"
        return f"{n:,}원"
    return f"{n:,}원"


def fmt_ratio(v, decimals: int = 2, suffix: str = "") -> str:
    """ROAS·배율 등 비율(숫자, 단위 없음). 소수점 둘째 자리."""
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v, decimals: int = 2) -> str:
    """퍼센트(%). 예) 12.84%"""
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_delta(v, decimals: int = 2) -> str:
    """변화율. 부호 강제. 예) +12.34% / -32.50%"""
    if v is None:
        return "—"
    try:
        f = float(v)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_count(v, suffix: str = "건") -> str:
    """건수·횟수. 천단위 콤마, 소수점 없음. 예) 1,234건"""
    if v is None:
        return "—"
    try:
        return f"{int(round(float(v))):,}{suffix}"
    except (TypeError, ValueError):
        return "—"


def fmt_days(v) -> str:
    """일수. 예) 10일. 이미 '10일' 문자열이면 그대로."""
    if v is None:
        return "—"
    s = str(v).strip()
    if s.endswith("일"):
        return s
    try:
        return f"{int(round(float(s)))}일"
    except (TypeError, ValueError):
        return s or "—"
