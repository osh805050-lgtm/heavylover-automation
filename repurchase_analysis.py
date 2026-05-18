"""재구매 분석 — GAS runAll() Python 재구현.

GAS repurchase_v5_1.gs → Python pandas-free 버전.
Apps Script 6분 execution timeout 제거 목적.

사용:
  python repurchase_analysis.py            # 실제 탭에 쓰기
  python repurchase_analysis.py --shadow   # py_ prefix 탭에 쓰기 (병행 검증)

환경변수:
  REPURCHASE_SHEET_ID, GOOGLE_SA_KEY_PATH
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import gspread
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

KST = timezone(timedelta(hours=9))

# ── 상수 ────────────────────────────────────────────────────────
CANCEL_KEYWORDS      = ["취소", "환불", "반품"]
COHORT_WINDOWS       = [30, 60, 90]
FUNNEL_MATURITY_DAYS = 10
MAX_MONTHS           = 13   # 최근 13개월

# GAS HL.CAFE24_COL (1-based → 0-based)
C24_ORDER_NO = 0
C24_DATE     = 1
C24_STATUS   = 2
C24_AMOUNT   = 3
C24_CUSTOMER = 4

# GAS HL.SS_COL (1-based → 0-based)
CSS_ORDER_NO = 1
CSS_STATUS   = 4
CSS_CUSTOMER = 8
CSS_AMOUNT   = 28
CSS_DATE     = 39

SHEET_ORDER = [
    "📊 통합 대시보드", "📊 대시보드 (카페24)", "📊 대시보드 (스마트스토어)",
    "재구매_통합_월별", "재구매_카페24_월별", "재구매_SS_월별",
    "재구매_통합_주별", "재구매_카페24_주별", "재구매_SS_주별",
    "재구매_통합_일별", "재구매_카페24_일별", "재구매_SS_일별",
    "코호트_통합_전환율", "코호트_카페24_전환율", "코호트_SS_전환율",
    "구매횟수_퍼널_통합", "구매횟수_퍼널_카페24", "구매횟수_퍼널_SS",
    "코호트_통합_월별잔존율", "코호트_카페24_월별잔존율", "코호트_SS_월별잔존율",
    "재구매_간격분석",
]


# ── 유틸 ────────────────────────────────────────────────────────

def _now_kst() -> datetime:
    return datetime.now(KST)


def _today_kst() -> date:
    return _now_kst().date()


def _parse_date(s) -> date | None:
    """날짜 파싱. str/datetime/date 모두 처리."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    s = str(s).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_datetime(s) -> datetime | None:
    """시각 포함 datetime 파싱. GAS sort와 동일하게 시각 기준 정렬 위해 사용."""
    if isinstance(s, datetime):
        return s
    if isinstance(s, date):
        return datetime(s.year, s.month, s.day)
    s = str(s).strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M")  # SS: "2025-10-21 1:44"
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


def is_canceled_status(status: str) -> bool:
    """GAS isCanceledStatus_() 대응. 공백 정규화 후 취소/환불/반품 부분일치."""
    s = status.strip()
    if not s:
        return True   # GAS: if (!s) return true
    return any(kw in s for kw in CANCEL_KEYWORDS)


def percentile(arr: list[int], p: int) -> int:
    """GAS pct2() 대응. ceil 방식."""
    if not arr:
        return 0
    s = sorted(arr)
    idx = math.ceil(len(s) * p / 100) - 1
    return s[max(0, min(idx, len(s) - 1))]


def week_start(d: date) -> date:
    """GAS weekStart() 대응. 월요일 기준. weekday() 0=월."""
    return d - timedelta(days=d.weekday())


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _add_months(yyyymm: str, n: int) -> str:
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    m += n
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


# ── 데이터 로드 ─────────────────────────────────────────────────

def load_cafe24_orders_from_rows(rows: list[list]) -> list[dict]:
    """GAS loadCafe24Orders() 대응.

    카페24: 첫 row만 저장 (sheets_sync.py [row]*n 복제로 item 수만큼 중복 방지).
    amount 누적 금지 — 3-item 주문 50,000원이 150,000원으로 부풀려짐.
    """
    if len(rows) < 2:
        return []
    order_map: dict[str, dict] = {}
    for row in rows[1:]:
        if len(row) <= C24_CUSTOMER:
            continue
        order_no = str(row[C24_ORDER_NO] or "").strip()
        date_raw = row[C24_DATE]
        status   = str(row[C24_STATUS] or "").strip()
        amount_s = str(row[C24_AMOUNT] or "").replace(",", "")
        phone    = str(row[C24_CUSTOMER] or "").strip()

        if not order_no or not date_raw or not phone:
            continue
        if is_canceled_status(status):
            continue
        if order_no in order_map:
            continue   # 첫 row만

        order_date = _parse_date(date_raw)
        if order_date is None:
            continue

        try:
            amount = int(float(re.sub(r"[^0-9.]", "", amount_s) or "0"))
        except ValueError:
            amount = 0

        customer = re.sub(r"\D", "", phone)
        if not customer:
            continue

        order_map[order_no] = {
            "order_no": order_no,
            "order_date": order_date,
            "order_datetime": _parse_datetime(date_raw),
            "amount": amount,
            "customer": customer,
            "platform": "cafe24",
        }
    return sorted(order_map.values(), key=lambda o: o["order_date"])


def load_ss_orders_from_rows(rows: list[list]) -> list[dict]:
    """GAS loadSSOrders() 대응.

    SS: 같은 orderNo 다중 row amount 누적.
    amount > 0 필터 (sheets_sync fallback이 0원 채움).
    """
    if len(rows) < 2:
        return []
    order_map: dict[str, dict] = {}
    for row in rows[1:]:
        if len(row) <= CSS_DATE:
            continue
        order_no = str(row[CSS_ORDER_NO] or "").strip()
        status   = str(row[CSS_STATUS]   or "").strip()
        customer = str(row[CSS_CUSTOMER] or "").strip()
        amount_s = str(row[CSS_AMOUNT]   or "").replace(",", "")
        date_raw = row[CSS_DATE]

        if not order_no or not date_raw:
            continue
        if is_canceled_status(status):
            continue

        try:
            amount = int(float(re.sub(r"[^0-9.]", "", amount_s) or "0"))
        except ValueError:
            amount = 0

        if amount <= 0:
            continue

        order_date = _parse_date(date_raw)
        if order_date is None:
            continue

        if order_no in order_map:
            order_map[order_no]["amount"] += amount   # SS: 누적
        else:
            order_map[order_no] = {
                "order_no": order_no,
                "order_date": order_date,
                "order_datetime": _parse_datetime(date_raw),
                "amount": amount,
                "customer": customer,
                "platform": "ss",
            }
    return sorted(order_map.values(), key=lambda o: o["order_date"])


def build_history(orders: list[dict]) -> dict[str, list[dict]]:
    """GAS buildHistory() 대응. customer → date 오름차순 주문 리스트."""
    h: dict[str, list[dict]] = {}
    for o in orders:
        h.setdefault(o["customer"], []).append(o)
    for lst in h.values():
        lst.sort(key=lambda o: (o["order_date"], o.get("order_datetime") or datetime.min))
    return h


def _bucket_key(d: date, period: str) -> str:
    if period == "D":
        return d.strftime("%Y-%m-%d")
    if period == "W":
        return week_start(d).strftime("%Y-%m-%d")
    return _month_key(d)


def build_buckets(orders: list[dict], period: str) -> dict[str, list[dict]]:
    """GAS buildBuckets() 대응."""
    b: dict[str, list[dict]] = {}
    for o in orders:
        key = _bucket_key(o["order_date"], period)
        b.setdefault(key, []).append(o)
    return dict(sorted(b.items()))


# ── gspread 헬퍼 ────────────────────────────────────────────────

def _get_or_create_ws(ss, name: str):
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=1000, cols=30)


def _safe_update(ws, data: list[list]) -> None:
    """clear → update. gspread quota 방어용 sleep 포함."""
    ws.clear()
    time.sleep(1.0)
    if data:
        ws.update(values=data, range_name="A1")
    time.sleep(0.5)


# ── 시트 쓰기 ───────────────────────────────────────────────────

def write_repurchase_sheet(
    ss, orders: list[dict], sheet_name: str, period: str
) -> None:
    """GAS writeRepurchaseSheet() 대응.

    분모 = dedup(신규∪재구매). sales-mix 재구매율.
    """
    all_history = build_history(orders)
    buckets = build_buckets(orders, period)

    # 헤더: repurchase_report.py _extract_monthly r[4]=AOV r[5]=재구매빈도 r[6]=재구매율 r[7]=신규구매자수
    header = ["기간", "재구매자수", "재구매건수", "재구매매출(원)",
              "AOV_재구매(원)", "재구매빈도", "재구매율(%,sales-mix)", "신규구매자수", "신규매출(원)"]
    rows = [header]

    for key in sorted(buckets.keys()):
        bucket_orders = buckets[key]
        new_cust: set[str] = set()
        rep_cust: set[str] = set()
        new_sales = 0
        rep_sales = 0
        rep_count = 0

        for o in bucket_orders:
            hist = all_history.get(o["customer"], [])
            # GAS: findIndex(날짜+orderNo 완전일치) → index<=0 신규, index>=1 재구매
            order_index = next(
                (i for i, h in enumerate(hist)
                 if h["order_date"] == o["order_date"] and h["order_no"] == o["order_no"]),
                -1
            )
            if order_index <= 0:
                new_cust.add(o["customer"])
                new_sales += o["amount"]
            else:
                rep_cust.add(o["customer"])
                rep_sales += o["amount"]
                rep_count += 1

        total_cust = len(new_cust | rep_cust)
        rep_rate = round(len(rep_cust) / total_cust * 100, 1) if total_cust else 0
        aov  = round(rep_sales / rep_count) if rep_count else 0
        freq = round(rep_count / len(rep_cust), 1) if rep_cust else 0
        rows.append([key, len(rep_cust), rep_count, rep_sales,
                     aov, freq, rep_rate, len(new_cust), new_sales])

    ws = _get_or_create_ws(ss, sheet_name)
    _safe_update(ws, rows)


def write_cohort_sheet(ss, orders: list[dict], sheet_name: str) -> None:
    """GAS writeCohortSheet() 대응. eligible = total - observing."""
    today = _today_kst()
    history = build_history(orders)

    cohort_map: dict[str, list[str]] = {}
    for cust, cust_orders in history.items():
        cm = _month_key(cust_orders[0]["order_date"])
        cohort_map.setdefault(cm, []).append(cust)

    # GAS 컬럼 순서: 코호트월 | 첫구매자수 | (30일전환수 | 30일전환율 | 30일관찰중) | (60일...) | (90일...)
    # repurchase_report.py r[2]=30일전환수 r[3]=30일전환율 r[5]=60일전환수 r[6]=60일전환율
    header = ["코호트월", "첫구매자수"]
    for w in COHORT_WINDOWS:
        header += [f"{w}일 전환수", f"{w}일 전환율(eligible)", f"{w}일 관찰중"]
    rows = [header]

    for cm in sorted(cohort_map.keys()):
        custs = cohort_map[cm]
        row: list = [cm, len(custs)]

        for window in COHORT_WINDOWS:
            converted = 0
            observing = 0
            for cust in custs:
                cust_orders = history[cust]
                first_date = cust_orders[0]["order_date"]
                first_order_no = cust_orders[0]["order_no"]
                deadline = first_date + timedelta(days=window)
                if deadline > today:
                    observing += 1
                    continue
                if any(o["order_no"] != first_order_no and o["order_date"] <= deadline
                       for o in cust_orders):
                    converted += 1
            eligible = len(custs) - observing
            rate = round(converted / eligible * 100, 1) if eligible > 0 else 0
            # GAS: observing=0이면 '✅', >0이면 숫자
            obs_display = "✅" if observing == 0 else observing
            rate_display = f"⏳ {rate}" if observing > 0 else f"{rate}%"
            row += [converted, rate_display, obs_display]

        rows.append(row)

    ws = _get_or_create_ws(ss, sheet_name)
    _safe_update(ws, rows)


def write_funnel_sheet(ss, orders: list[dict], sheet_name: str) -> None:
    """GAS writePurchaseFunnelSheet() 대응. maturity_days=10."""
    today = _today_kst()
    history = build_history(orders)

    # 단계별 고객 분류
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for cust, cust_orders in history.items():
        n = min(len(cust_orders), 4)
        counts[n] = counts.get(n, 0) + 1

    # 단계 전환율 + 소요일 (maturity window 10일 적용)
    stage_data = []
    for stage in [(1, 2), (2, 3), (3, 4)]:
        from_n, to_n = stage
        gaps = []
        observing = 0
        eligible_base = 0

        for cust, cust_orders in history.items():
            if len(cust_orders) < from_n:
                continue
            eligible_base += 1
            last_of_from = cust_orders[from_n - 1]["order_date"]
            deadline = last_of_from + timedelta(days=FUNNEL_MATURITY_DAYS)
            if deadline > today:
                observing += 1
                continue
            if len(cust_orders) >= to_n:
                gap = (cust_orders[to_n - 1]["order_date"] - last_of_from).days
                gaps.append(max(0, gap))

        eligible = eligible_base - observing
        conv_rate = round(len(gaps) / eligible * 100, 1) if eligible > 0 else 0
        p50 = percentile(gaps, 50) if gaps else 0
        p75 = percentile(gaps, 75) if gaps else 0
        stage_data.append([f"{from_n}→{to_n}", eligible, observing,
                           len(gaps), conv_rate, p50, p75])

    header = [["단계", "기준(eligible)", "관찰중", "전환고객수", "전환율(%)", "P50소요일", "P75소요일"]]
    ws = _get_or_create_ws(ss, sheet_name)
    _safe_update(ws, header + stage_data)


def write_retention_sheet(ss, orders: list[dict], sheet_name: str) -> None:
    """GAS writeMonthlyRetentionSheet() 대응. M+1~M+12. 현재월 🔵 표시."""
    today = _today_kst()
    current_month = _month_key(today)
    history = build_history(orders)

    cohort_map: dict[str, list[str]] = {}
    for cust, cust_orders in history.items():
        cm = _month_key(cust_orders[0]["order_date"])
        cohort_map.setdefault(cm, []).append(cust)

    header = ["코호트월", "첫구매자수"] + [f"M+{i}" for i in range(1, MAX_MONTHS)]
    rows = [header]

    for cm in sorted(cohort_map.keys()):
        custs = cohort_map[cm]
        row: list = [cm, len(custs)]
        for mn in range(1, MAX_MONTHS):
            target_month = _add_months(cm, mn)
            if target_month > current_month:
                row.append("─")
                continue
            retained = 0
            for cust in custs:
                if any(_month_key(o["order_date"]) == target_month
                       for o in history[cust][1:]):
                    retained += 1
            rate = round(retained / len(custs) * 100, 1) if custs else 0
            if target_month == current_month:
                row.append(f"🔵 {rate}")
            else:
                row.append(rate)
        rows.append(row)

    ws = _get_or_create_ws(ss, sheet_name)
    _safe_update(ws, rows)


def write_interval_sheet(ss, orders: list[dict], sheet_name: str = "재구매_간격분석") -> None:
    """GAS writeIntervalSheet() 대응. key 문자열은 repurchase_report.py와 부분매칭.

    sheet_name 인자: shadow 모드에서 'py_재구매_간격분석'으로 전달 가능.
    """
    history = build_history(orders)
    all_gaps: list[int] = []
    first_gaps: list[int] = []

    for cust_orders in history.values():
        dates = [o["order_date"] for o in cust_orders]
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap >= 0:   # GAS: d >= 0 (0일 포함)
                all_gaps.append(gap)
        if len(dates) >= 2:
            first_gaps.append((dates[1] - dates[0]).days)

    data = [
        ["지표", "값", "설명"],
        ["중앙값 P50 (1→2 첫 재구매)", f"{percentile(first_gaps, 50)}일", "★ CRM 리마인드 발송 타이밍 기준"],
        ["P75 (1→2 첫 재구매)",        f"{percentile(first_gaps, 75)}일", "1→2 75% 고객이 이 일수 이내"],
        ["P90 (1→2 첫 재구매)",        f"{percentile(first_gaps, 90)}일", "1→2 90% 고객이 이 일수 이내"],
        ["샘플 수 (1→2 전용)",          str(len(first_gaps)),             "1→2 첫 재구매 간격 집계 고객 수"],
        ["중앙값 (P50, 전체)",           f"{percentile(all_gaps, 50)}일",  "50% 고객이 이 일수 이내 재구매"],
        ["P75 (전체)",                   f"{percentile(all_gaps, 75)}일",  "75% 고객이 이 일수 이내 재구매"],
        ["P90 ← CRM 기준 (전체)",        f"{percentile(all_gaps, 90)}일",  "▶ SMS 재구매 유도 발송 기준 추천"],
    ]
    ws = _get_or_create_ws(ss, sheet_name)
    _safe_update(ws, data)


def reorder_sheets(ss) -> None:
    """GAS reorderSheets() 대응."""
    all_ws = {ws.title: ws for ws in ss.worksheets()}
    ordered = [all_ws[name] for name in SHEET_ORDER if name in all_ws]
    rest = [ws for ws in ss.worksheets() if ws.title not in SHEET_ORDER]
    try:
        ss.reorder_worksheets(ordered + rest)
    except Exception:
        pass   # 권한 없으면 skip


# ── 진입점 ──────────────────────────────────────────────────────

def _open_sheet():
    """sheets_sync.py _open_sheet() 와 동일 패턴."""
    from google.oauth2.service_account import Credentials
    SCOPES = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    key_path = os.getenv("GOOGLE_SA_KEY_PATH", "")
    sheet_id = os.getenv("REPURCHASE_SHEET_ID", "")
    if not sheet_id:
        raise RuntimeError("REPURCHASE_SHEET_ID 미설정")
    creds = Credentials.from_service_account_file(key_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def run_all(shadow: bool = False) -> dict:
    """GAS runAll() Python 대체. pipeline_meta에 writer='analysis' 기록."""
    from lib.sheet_staleness import write_pipeline_meta_row

    ss = _open_sheet()
    run_id     = _now_kst().strftime("%Y-%m-%d_%H%M%S") + "_analysis"
    started_at = _now_kst().strftime("%Y-%m-%d %H:%M:%S")

    write_pipeline_meta_row(ss, "analysis", run_id, started_at, "", "running")

    try:
        # 소스 탭 검증
        cafe24_ws = ss.worksheet("카페24 재구매매출")
        ss_ws     = ss.worksheet("스마트스토어 재구매매출")

        cafe24_rows = cafe24_ws.get_all_values()
        ss_rows     = ss_ws.get_all_values()

        if len(cafe24_rows) < 2:
            raise RuntimeError("카페24 재구매매출 데이터 없음 — sheets_sync 미완료 가능성")

        cafe24    = load_cafe24_orders_from_rows(cafe24_rows)
        ss_orders = load_ss_orders_from_rows(ss_rows)
        all_ord   = cafe24 + ss_orders

        px = "py_" if shadow else ""   # shadow 모드: py_ prefix

        # 재구매 지표 9개
        for orders, ch in [(cafe24, "카페24"), (ss_orders, "SS"), (all_ord, "통합")]:
            for period, suffix in [("D", "일별"), ("W", "주별"), ("M", "월별")]:
                write_repurchase_sheet(ss, orders, f"{px}재구매_{ch}_{suffix}", period)

        # 코호트 전환율 3개
        for orders, ch in [(cafe24, "카페24"), (ss_orders, "SS"), (all_ord, "통합")]:
            write_cohort_sheet(ss, orders, f"{px}코호트_{ch}_전환율")

        # 구매횟수 퍼널 3개
        for orders, ch in [(cafe24, "카페24"), (ss_orders, "SS"), (all_ord, "통합")]:
            write_funnel_sheet(ss, orders, f"{px}구매횟수_퍼널_{ch}")

        # 월별 잔존율 3개
        for orders, ch in [(cafe24, "카페24"), (ss_orders, "SS"), (all_ord, "통합")]:
            write_retention_sheet(ss, orders, f"{px}코호트_{ch}_월별잔존율")

        # 재구매 간격분석 1개 — shadow 모드는 py_ prefix로 분리
        write_interval_sheet(ss, all_ord, f"{px}재구매_간격분석")

        if not shadow:
            reorder_sheets(ss)

        finished_at = _now_kst().strftime("%Y-%m-%d %H:%M:%S")
        write_pipeline_meta_row(ss, "analysis", run_id, started_at, finished_at, "success")
        print(f"[OK] cafe24={len(cafe24)} ss={len(ss_orders)}", flush=True)
        return {"status": "success", "cafe24": len(cafe24), "ss": len(ss_orders)}

    except Exception as e:
        finished_at = _now_kst().strftime("%Y-%m-%d %H:%M:%S")
        write_pipeline_meta_row(ss, "analysis", run_id, started_at, finished_at, "fail",
                                extra=str(e)[:300])
        print(f"[FAIL] {e}", flush=True)
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow", action="store_true",
                        help="py_ prefix 탭에 쓰기 (병행 검증 모드)")
    args = parser.parse_args()
    run_all(shadow=args.shadow)
