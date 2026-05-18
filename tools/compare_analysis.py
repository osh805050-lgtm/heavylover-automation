"""shadow(py_) vs GAS 수치 비교. 불일치 시 ops 텔레그램 알림.

매일 08:55 cron으로 실행 (GAS 08:00~08:50 완료 + Python --shadow 08:45 완료 후).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# 비교 대상 12쌍 (GAS 탭명 ↔ Python shadow 탭명)
TAB_PAIRS = [
    # 월별: YYYY-MM 키 — JOIN 가능
    ("재구매_통합_월별",   "py_재구매_통합_월별"),
    ("재구매_카페24_월별", "py_재구매_카페24_월별"),
    ("재구매_SS_월별",     "py_재구매_SS_월별"),
    # 코호트: YYYY-MM 키 — JOIN 가능
    ("코호트_통합_전환율", "py_코호트_통합_전환율"),
    ("코호트_카페24_전환율","py_코호트_카페24_전환율"),
    ("코호트_SS_전환율",   "py_코호트_SS_전환율"),
    # 주별(YYYY-MM-DD 키)·퍼널(1회/2회 키) → 포맷 불일치로 자동 비교 제외
]

# 허용 오차
TOLERANCE_PCT = 0.2   # 비율 지표 ±0.2%p
TOLERANCE_INT = 1     # 정수 지표 ±1 (반올림 차이)


def _to_num(s) -> float | None:
    """문자열 → float. '⏳ 14.5' 또는 '🔵 17.5' 같은 prefix 제거."""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ("─", "—", "-"):
        return None
    # prefix 제거 (⏳, 🔵 등 이모지)
    for prefix in ("⏳", "🔵", "★", "✅", "▶"):
        s = s.replace(prefix, "").strip()
    s = s.replace(",", "").replace("%", "").replace("일", "").replace("원", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _keyed_rows(all_values: list[list]) -> dict[str, list]:
    """YYYY-MM 또는 YYYY-M 형태 첫 컬럼 행만 추출 → {YYYY-MM: row}."""
    import re
    result = {}
    for row in all_values:
        if not row or not row[0]:
            continue
        key = str(row[0]).strip()
        if re.match(r"^\d{4}-\d{1,2}$", key):
            parts = key.split("-")
            norm = f"{parts[0]}-{parts[1].zfill(2)}"
            result[norm] = row
    return result


def compare_tabs(ss, gas_name: str, py_name: str) -> list[str]:
    """두 탭을 YYYY-MM 키로 JOIN해서 숫자 비교. 최근 3개월 관찰중 행은 제외."""
    import gspread
    from datetime import datetime as _dt
    issues: list[str] = []
    try:
        gas_ws = ss.worksheet(gas_name)
    except gspread.WorksheetNotFound:
        return [f"{gas_name} 탭 없음 (GAS 미생성)"]
    try:
        py_ws = ss.worksheet(py_name)
    except gspread.WorksheetNotFound:
        return [f"{py_name} 탭 없음 (Python --shadow 미실행)"]

    time.sleep(0.5)
    gas_dict = _keyed_rows(gas_ws.get_all_values())
    time.sleep(0.5)
    py_dict  = _keyed_rows(py_ws.get_all_values())

    if not gas_dict or not py_dict:
        return [f"{gas_name}: 데이터 없음"]

    # 6개월 이전 확정 행만 비교 (최근 코호트는 관찰중 변동으로 차이 허용)
    now = _dt.now()
    m = now.month - 6
    y = now.year if m > 0 else now.year - 1
    m = m if m > 0 else m + 12
    cutoff_ym = f"{y}-{str(m).zfill(2)}"
    stable_keys = sorted(k for k in set(gas_dict) & set(py_dict) if k < cutoff_ym)

    for key in stable_keys:
        g_row = gas_dict[key]
        p_row = py_dict[key]
        cols  = min(len(g_row), len(p_row))
        for col_idx in range(1, cols):
            gv = _to_num(g_row[col_idx])
            pv = _to_num(p_row[col_idx])
            if gv is None or pv is None:
                continue
            tol = TOLERANCE_PCT if abs(gv) < 100 else TOLERANCE_INT
            if abs(gv - pv) > tol:
                diff = abs(gv - pv)
                issues.append(
                    f"{gas_name} {key} col{col_idx}: GAS={gv} Python={pv} (diff={diff:.1f})"
                )
    return issues


def main() -> int:
    from repurchase_analysis import _open_sheet
    from telegram_client import send_message

    ss = _open_sheet()
    all_issues: list[str] = []
    checked = 0

    for gas_name, py_name in TAB_PAIRS:
        issues = compare_tabs(ss, gas_name, py_name)
        if issues:
            all_issues.extend(issues)
        else:
            checked += 1
        time.sleep(0.5)

    if all_issues:
        msg = (
            "[불일치] Python 분석 검증 불일치 ({0}건)\n"
            "\n"
            "통과 탭: {1}/{2}\n"
            "\n"
            "불일치 (최대 8건):\n"
        ).format(len(all_issues), checked, len(TAB_PAIRS))
        msg += "\n".join(f"- {x}" for x in all_issues[:8])
        msg += "\n\n대응: Claude에 점검 요청"
        try:
            send_message(msg, channel="ops")
        except Exception as e:
            print(f"텔레그램 발송 실패: {e}", flush=True)
        print(msg, flush=True)
        return 1
    else:
        print(f"[OK] 비교 통과 {checked}/{len(TAB_PAIRS)} 탭", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
