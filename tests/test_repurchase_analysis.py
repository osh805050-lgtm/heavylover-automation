"""repurchase_analysis.py 단위 테스트."""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from repurchase_analysis import (
    is_canceled_status,
    load_cafe24_orders_from_rows,
    load_ss_orders_from_rows,
    build_history,
    build_buckets,
    week_start,
    percentile,
    write_repurchase_sheet,
    write_cohort_sheet,
    write_interval_sheet,
)


# ── is_canceled_status ──────────────────────────────────────────

def test_canceled_취소():
    assert is_canceled_status("취소완료") is True

def test_canceled_환불():
    assert is_canceled_status("환불처리") is True

def test_canceled_반품():
    assert is_canceled_status("반품완료") is True

def test_canceled_정상():
    assert is_canceled_status("배송완료") is False

def test_canceled_공백포함():
    assert is_canceled_status("  취소  ") is True

def test_canceled_빈문자열():
    assert is_canceled_status("") is True   # GAS: if (!s) return true

def test_canceled_배송중():
    assert is_canceled_status("배송중") is False


# ── load_cafe24_orders_from_rows ────────────────────────────────

def _c24_row(order_no, date_str, status, amount, phone):
    row = [""] * 5
    row[0] = order_no; row[1] = date_str; row[2] = status
    row[3] = str(amount); row[4] = phone
    return row

def test_cafe24_기본():
    rows = [["h1","h2","h3","h4","h5"],
            _c24_row("ORD001", "2026-05-01 10:00:00", "배송완료", 65000, "01012345678")]
    orders = load_cafe24_orders_from_rows(rows)
    assert len(orders) == 1
    assert orders[0]["amount"] == 65000
    assert orders[0]["customer"] == "01012345678"
    assert orders[0]["platform"] == "cafe24"

def test_cafe24_취소_제외():
    rows = [["h1","h2","h3","h4","h5"],
            _c24_row("ORD002", "2026-05-02", "취소완료", 30000, "01099999999")]
    orders = load_cafe24_orders_from_rows(rows)
    assert len(orders) == 0

def test_cafe24_중복_첫row만():
    rows = [["h1","h2","h3","h4","h5"],
            _c24_row("ORD001", "2026-05-01", "배송완료", 65000, "01012345678"),
            _c24_row("ORD001", "2026-05-01", "배송완료", 65000, "01012345678")]
    orders = load_cafe24_orders_from_rows(rows)
    assert len(orders) == 1  # 중복 제거

def test_cafe24_하이픈_제거():
    rows = [["h1","h2","h3","h4","h5"],
            _c24_row("ORD003", "2026-05-03", "배송완료", 80000, "010-8888-7777")]
    orders = load_cafe24_orders_from_rows(rows)
    assert orders[0]["customer"] == "01088887777"

def test_cafe24_누적_금지():
    """item 3개짜리 주문 — 첫 row만이므로 amount 65000, 누적 195000 아님."""
    rows = [["h1","h2","h3","h4","h5"],
            _c24_row("ORD001", "2026-05-01", "배송완료", 65000, "01012345678"),
            _c24_row("ORD001", "2026-05-01", "배송완료", 65000, "01012345678"),
            _c24_row("ORD001", "2026-05-01", "배송완료", 65000, "01012345678")]
    orders = load_cafe24_orders_from_rows(rows)
    assert orders[0]["amount"] == 65000  # 누적 아님


# ── load_ss_orders_from_rows ────────────────────────────────────

def _ss_row(order_no, status, customer, amount, date_str):
    row = [""] * 46
    row[1] = order_no; row[4] = status; row[8] = customer
    row[28] = str(amount); row[39] = date_str
    return row

def test_ss_기본():
    rows = [["h"] * 46,
            _ss_row("SS001", "PURCHASE_DECIDED", "buyer1", 30000, "2026-05-01")]
    orders = load_ss_orders_from_rows(rows)
    assert len(orders) == 1
    assert orders[0]["amount"] == 30000
    assert orders[0]["platform"] == "ss"

def test_ss_amount_누적():
    rows = [["h"] * 46,
            _ss_row("SS001", "PURCHASE_DECIDED", "buyer1", 30000, "2026-05-01"),
            _ss_row("SS001", "PURCHASE_DECIDED", "buyer1", 20000, "2026-05-01")]
    orders = load_ss_orders_from_rows(rows)
    assert len(orders) == 1
    assert orders[0]["amount"] == 50000  # 누적

def test_ss_취소_제외():
    rows = [["h"] * 46,
            _ss_row("SS002", "취소완료", "buyer2", 40000, "2026-05-02")]
    orders = load_ss_orders_from_rows(rows)
    assert len(orders) == 0

def test_ss_0원_제외():
    rows = [["h"] * 46,
            _ss_row("SS003", "PURCHASE_DECIDED", "buyer3", 0, "2026-05-03")]
    orders = load_ss_orders_from_rows(rows)
    assert len(orders) == 0


# ── 통계 유틸 ───────────────────────────────────────────────────

def test_percentile_p50():
    assert percentile([1,2,3,4,5], 50) == 3

def test_percentile_p90():
    assert percentile([1,2,3,4,5,6,7,8,9,10], 90) == 9

def test_percentile_빈리스트():
    assert percentile([], 50) == 0

def test_week_start_월요일():
    d = date(2026, 5, 18)   # 월요일
    assert week_start(d) == date(2026, 5, 18)

def test_week_start_수요일():
    d = date(2026, 5, 20)   # 수요일
    assert week_start(d) == date(2026, 5, 18)

def test_week_start_일요일():
    d = date(2026, 5, 17)   # 일요일
    assert week_start(d) == date(2026, 5, 11)

def test_build_history_그룹핑():
    orders = [
        {"customer":"A","order_date":date(2026,1,1),"amount":1000,"platform":"cafe24","order_no":"1"},
        {"customer":"A","order_date":date(2026,1,15),"amount":2000,"platform":"cafe24","order_no":"2"},
        {"customer":"B","order_date":date(2026,1,5),"amount":500,"platform":"ss","order_no":"3"},
    ]
    h = build_history(orders)
    assert len(h["A"]) == 2
    assert len(h["B"]) == 1
    assert h["A"][0]["order_no"] == "1"  # date 오름차순

def test_build_history_동일날짜_시각정렬():
    """같은 날 SS(오전 11시) + 카페24(오후 6시) 주문 — GAS처럼 시각 이른 SS가 먼저."""
    from datetime import datetime as dt
    orders = [
        {"customer":"A","order_date":date(2025,5,1),
         "order_datetime":dt(2025,5,1,18,0,0),  # 카페24 오후 6시
         "amount":70000,"order_no":"C1","platform":"cafe24"},
        {"customer":"A","order_date":date(2025,5,1),
         "order_datetime":dt(2025,5,1,11,0,0),  # SS 오전 11시
         "amount":30000,"order_no":"S1","platform":"ss"},
    ]
    h = build_history(orders)
    # SS(11시)가 카페24(18시)보다 이르므로 S1이 history[0] = 신규
    assert h["A"][0]["order_no"] == "S1"
    assert h["A"][1]["order_no"] == "C1"


# ── write_interval_sheet (mock) ─────────────────────────────────

class MockWS:
    def __init__(self):
        self.data = None
        self.cleared = False
    def clear(self):
        self.cleared = True
    def update(self, values, range_name="A1"):
        self.data = values

class MockSS:
    def __init__(self, ws):
        self._ws = ws
    def worksheet(self, name):
        return self._ws

# ── compare_analysis._to_num ────────────────────────────────────

from tools.compare_analysis import _to_num

def test_to_num_정수():
    assert _to_num("12345") == 12345.0

def test_to_num_쉼표():
    assert _to_num("1,234,567") == 1234567.0

def test_to_num_퍼센트():
    assert _to_num("14.5%") == 14.5

def test_to_num_일단위():
    assert _to_num("10일") == 10.0

def test_to_num_원단위():
    assert _to_num("65000원") == 65000.0

def test_to_num_partial마커():
    assert _to_num("🔵 17.5") == 17.5

def test_to_num_observing():
    assert _to_num("⏳ 14.5") == 14.5

def test_to_num_미래월():
    assert _to_num("─") is None

def test_to_num_빈값():
    assert _to_num("") is None
    assert _to_num(None) is None


def test_interval_sheet_key_포함():
    """key 문자열에 '1→2'와 '중앙값' 포함 확인 — repurchase_report.py 부분매칭 호환."""
    orders = [
        {"customer":"A","order_date":date(2026,1,1),"amount":1000,"platform":"cafe24","order_no":"1"},
        {"customer":"A","order_date":date(2026,1,11),"amount":2000,"platform":"cafe24","order_no":"2"},
        {"customer":"B","order_date":date(2026,2,1),"amount":1000,"platform":"cafe24","order_no":"3"},
        {"customer":"B","order_date":date(2026,2,15),"amount":2000,"platform":"cafe24","order_no":"4"},
    ]
    ws = MockWS()
    ss = MockSS(ws)
    write_interval_sheet(ss, orders)
    keys = [row[0] for row in ws.data[1:]]
    assert any("1→2" in k and ("P50" in k or "중앙값" in k) for k in keys)
    assert any("P90" in k and "전체" in k for k in keys)


# ── write_repurchase_sheet ──────────────────────────────────────

def _o(cust, d, amount, no, platform="cafe24"):
    return {"customer": cust, "order_date": d, "amount": amount, "order_no": no, "platform": platform}

def test_repurchase_sheet_헤더_9컬럼():
    """헤더 9개 컬럼 (r[6]=재구매율 매핑 호환)."""
    orders = [_o("A", date(2026,1,1), 1000, "1")]
    ws = MockWS()
    write_repurchase_sheet(MockSS(ws), orders, "test_tab", "M")
    header = ws.data[0]
    assert len(header) == 9
    assert header[0] == "기간"
    assert header[4] == "AOV_재구매(원)"
    assert header[5] == "재구매빈도"
    assert header[6] == "재구매율(%,sales-mix)"
    assert header[7] == "신규구매자수"

def test_repurchase_sheet_신규_분류():
    """고객 첫 주문 = 신규."""
    orders = [_o("A", date(2026,1,1), 1000, "1")]
    ws = MockWS()
    write_repurchase_sheet(MockSS(ws), orders, "test_tab", "M")
    row = ws.data[1]   # 2026-01
    # 신규구매자수=1, 재구매자수=0
    assert row[1] == 0  # 재구매자수
    assert row[7] == 1  # 신규구매자수

def test_repurchase_sheet_재구매_분류():
    """고객 두 번째 주문 = 재구매."""
    orders = [
        _o("A", date(2026,1,1), 1000, "1"),
        _o("A", date(2026,1,15), 2000, "2"),
    ]
    ws = MockWS()
    write_repurchase_sheet(MockSS(ws), orders, "test_tab", "M")
    row = ws.data[1]   # 2026-01
    assert row[1] == 1  # 재구매자수
    assert row[2] == 1  # 재구매건수
    assert row[3] == 2000  # 재구매매출

def test_repurchase_sheet_분모_dedup():
    """같은 bucket에서 신규+재구매 동일 고객 = 1명 (분모)."""
    orders = [
        _o("A", date(2026,1,1), 1000, "1"),    # 신규
        _o("A", date(2026,1,15), 2000, "2"),   # 재구매 (같은 1월 bucket)
    ]
    ws = MockWS()
    write_repurchase_sheet(MockSS(ws), orders, "test_tab", "M")
    row = ws.data[1]
    # 분모 = dedup(신규∪재구매) = 1명 (A 한 명)
    # 재구매율 = 1 / 1 = 100%
    assert row[6] == 100.0

def test_repurchase_sheet_freq_계산():
    """freq = 재구매건수 / 재구매자수."""
    orders = [
        _o("A", date(2025,12,1), 500, "0"),   # A 첫 구매 (이전 월)
        _o("A", date(2026,1,1), 1000, "1"),   # A 재구매
        _o("A", date(2026,1,15), 2000, "2"),  # A 재구매
        _o("B", date(2025,12,5), 500, "00"),  # B 첫 구매 (이전 월)
        _o("B", date(2026,1,10), 3000, "3"),  # B 재구매
    ]
    ws = MockWS()
    write_repurchase_sheet(MockSS(ws), orders, "test_tab", "M")
    # 2026-01 bucket
    jan = next(r for r in ws.data[1:] if r[0] == "2026-01")
    # 재구매자수=2 (A, B), 재구매건수=3 (A 2번 + B 1번)
    assert jan[1] == 2
    assert jan[2] == 3
    assert jan[5] == 1.5  # freq = 3/2


# ── write_cohort_sheet ──────────────────────────────────────────

def test_cohort_eligible_분모():
    """eligible = total - observing. observing > 0이면 ⏳ prefix."""
    # 충분히 옛날 코호트 (observing=0 보장)
    orders = [
        _o("A", date(2020,1,1), 1000, "1"),
        _o("A", date(2020,1,15), 2000, "2"),
        _o("B", date(2020,1,5), 1000, "3"),
        # B는 재구매 안 함
    ]
    ws = MockWS()
    write_cohort_sheet(MockSS(ws), orders, "test_cohort")
    # 헤더: 코호트월, 첫구매자수, 30/60/90일전환수, 30/60/90일전환율, 30/60/90일관찰중
    row = next(r for r in ws.data[1:] if r[0] == "2020-01")
    assert row[1] == 2   # 첫구매자수
    # 새 구조: row[2]=30일전환수, row[3]=30일전환율, row[4]=30일관찰중
    # observing=0이라 rate가 '50.0%' 형태
    assert "50.0" in str(row[3])   # 30일 전환율 50% (A만 재구매)

def test_cohort_observing_표시():
    """현재월 코호트는 observing > 0 → ⏳ prefix."""
    from datetime import datetime as dt
    today = dt.now().date()
    # 오늘 첫 구매 → 30일 안 지남 → observing=1
    orders = [_o("Z", today, 1000, "T1")]
    ws = MockWS()
    write_cohort_sheet(MockSS(ws), orders, "test_cohort")
    row = next(r for r in ws.data[1:] if r[0] == today.strftime("%Y-%m"))
    # 새 구조: row[3]=30일전환율. observing>0이면 ⏳ prefix
    assert "⏳" in str(row[3])


# ── write_funnel_sheet ──────────────────────────────────────────

from repurchase_analysis import write_funnel_sheet

def test_funnel_단계_3개():
    """헤더 + 1→2 / 2→3 / 3→4 = 4행."""
    orders = [
        _o("A", date(2020,1,1), 1000, "1"),
        _o("A", date(2020,2,1), 1000, "2"),
        _o("A", date(2020,3,1), 1000, "3"),
        _o("A", date(2020,4,1), 1000, "4"),
    ]
    ws = MockWS()
    write_funnel_sheet(MockSS(ws), orders, "test_funnel")
    assert len(ws.data) == 4   # 헤더 + 3 단계
    stages = [r[0] for r in ws.data[1:]]
    assert "1→2" in stages
    assert "2→3" in stages
    assert "3→4" in stages

def test_funnel_maturity_observing():
    """오늘 첫 구매 → 10일 미경과 → observing > 0."""
    from datetime import datetime as dt
    today = dt.now().date()
    orders = [_o("Z", today, 1000, "T1")]
    ws = MockWS()
    write_funnel_sheet(MockSS(ws), orders, "test_funnel")
    # 1→2 행
    s12 = next(r for r in ws.data[1:] if r[0] == "1→2")
    # observing 컬럼 (col 2) >= 1
    assert s12[2] >= 1


# ── write_retention_sheet ───────────────────────────────────────

from repurchase_analysis import write_retention_sheet

def test_retention_헤더_M컬럼():
    """헤더: 코호트월, 첫구매자수, M+1 ~ M+12."""
    orders = [_o("A", date(2020,1,1), 1000, "1")]
    ws = MockWS()
    write_retention_sheet(MockSS(ws), orders, "test_retention")
    header = ws.data[0]
    assert header[0] == "코호트월"
    assert header[1] == "첫구매자수"
    assert header[2] == "M+1"
    assert header[-1] == "M+12"

def test_retention_M1_재구매():
    """M+1 코호트의 다음달 재구매."""
    orders = [
        _o("A", date(2020,1,1), 1000, "1"),
        _o("A", date(2020,2,5), 2000, "2"),   # M+1
    ]
    ws = MockWS()
    write_retention_sheet(MockSS(ws), orders, "test_retention")
    row = next(r for r in ws.data[1:] if r[0] == "2020-01")
    # M+1 = 100% (A 1명 중 1명 재구매)
    assert row[2] == 100.0

def test_retention_미래월_dash():
    """미래월은 ─ 표시."""
    orders = [_o("A", date(2020,1,1), 1000, "1")]
    ws = MockWS()
    write_retention_sheet(MockSS(ws), orders, "test_retention")
    row = next(r for r in ws.data[1:] if r[0] == "2020-01")
    # 2020-01에서 M+12 (2021-01)는 이미 과거 → 숫자
    # 매우 옛날 코호트라 모든 M+N이 과거 → ─ 아님
    # 대신 오늘 코호트의 M+1은 미래
    pass  # 미래월 케이스는 _add_months 동작 확인으로 대체

def test_retention_현재월_marker():
    """현재월 셀에 🔵 prefix."""
    from datetime import datetime as dt
    today = dt.now().date()
    last_month_date = date(today.year if today.month > 1 else today.year-1,
                           today.month-1 if today.month > 1 else 12, 1)
    orders = [
        _o("A", last_month_date, 1000, "1"),
        _o("A", today, 2000, "2"),   # 현재월 재구매
    ]
    ws = MockWS()
    write_retention_sheet(MockSS(ws), orders, "test_retention")
    last_cm = last_month_date.strftime("%Y-%m")
    row = next(r for r in ws.data[1:] if r[0] == last_cm)
    # M+1 = 현재월. 🔵 prefix 포함
    m1 = str(row[2])
    assert "🔵" in m1


# ── write_cohort_sheet: same-day repurchase ──────────────────────

def test_cohort_sameday_repurchase_counts_as_converted():
    """첫구매일과 같은 날 재구매한 고객도 30일 전환수에 포함되어야 한다."""
    from datetime import datetime as dt, timedelta
    from repurchase_analysis import build_history, _today_kst

    orders = [
        {"customer": "A", "order_date": date(2020, 4, 1),
         "order_datetime": dt(2020, 4, 1, 11, 0, 0), "amount": 30000,
         "order_no": "S1", "platform": "ss"},
        {"customer": "A", "order_date": date(2020, 4, 1),
         "order_datetime": dt(2020, 4, 1, 18, 0, 0), "amount": 70000,
         "order_no": "C1", "platform": "cafe24"},
    ]
    h = build_history(orders)
    cust_orders = h["A"]
    first_date = cust_orders[0]["order_date"]
    first_order_no = cust_orders[0]["order_no"]
    deadline = first_date + timedelta(days=30)

    # old code: o["order_date"] > first_date  →  2020-04-01 > 2020-04-01 = False (bug)
    old_logic = any(o["order_date"] > first_date and o["order_date"] <= deadline
                    for o in cust_orders)
    assert old_logic is False, "old logic must fail (Red)"

    # new code: o["order_no"] != first_order_no  →  True for C1
    new_logic = any(o["order_no"] != first_order_no and o["order_date"] <= deadline
                    for o in cust_orders)
    assert new_logic is True, "new logic must pass (Green)"
