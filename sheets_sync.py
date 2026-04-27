"""재구매 분석 시트 자동 이관.

매일 08:30 실행. 카페24 + 스마트스토어 원본 탭에 최근 N일치 데이터를 덮어쓴다.
- 최근 N일 윈도우를 먼저 지우고, API에서 다시 받아와 append
- 취소/환불이 뒤늦게 반영되어도 정확히 동기화됨

.env 필요 값:
- GOOGLE_SA_KEY_PATH
- REPURCHASE_SHEET_ID
- CAFE24_*, NAVER_*, PROXY_* (기존)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

import cafe24_client
import naver_client

KST = timezone(timedelta(hours=9))
BACKFILL_DAYS = 7  # 이 기간 내 행은 매일 지우고 다시 넣음

ENV_PATH = Path(__file__).parent / ".env"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 탭 식별용 헤더 (첫 컬럼명)
CAFE24_HEADER_FIRST = "주문번호"
CAFE24_HEADER_SECOND = "결제일시(입금확인일)"
SS_HEADER_FIRST = "상품주문번호"


def _log(msg: str):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {msg}", flush=True)


def _get_sheets_client():
    load_dotenv(ENV_PATH, override=True)
    key_path = os.getenv("GOOGLE_SA_KEY_PATH", "")

    # 1) env에 지정된 경로가 존재하면 그대로
    if key_path and Path(key_path).exists():
        pass
    else:
        # 2) 로컬 폴더에 gcp-service-account.json 있으면 폴백
        local = Path(__file__).parent / "gcp-service-account.json"
        if local.exists():
            key_path = str(local)
        else:
            raise RuntimeError(
                f"서비스 계정 키를 찾지 못했습니다. "
                f"GOOGLE_SA_KEY_PATH={key_path!r} 또는 {local} 중 하나가 필요합니다."
            )

    creds = Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_sheet():
    client = _get_sheets_client()
    load_dotenv(ENV_PATH, override=True)
    sheet_id = os.getenv("REPURCHASE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("REPURCHASE_SHEET_ID 미설정")
    return client.open_by_key(sheet_id)


def _find_tab(spreadsheet, expected_first: str, expected_second: str | None = None):
    """첫 컬럼명(과 선택적으로 두 번째)으로 탭을 찾는다."""
    for ws in spreadsheet.worksheets():
        try:
            hdr = ws.row_values(1)
        except Exception:
            continue
        if not hdr:
            continue
        if hdr[0].strip() != expected_first:
            continue
        if expected_second and (len(hdr) < 2 or hdr[1].strip() != expected_second):
            continue
        return ws
    return None


# ============================================================
# 카페24
# ============================================================

def cafe24_order_to_rows(order: dict) -> list[list]:
    """카페24 order → 5컬럼 행들 (아이템 개수만큼 row 복제).

    엑셀 다운로드 포맷과 동일하게 (주문번호/결제일시/주문상태/실결제금액/주문자휴대전화).
    """
    if order.get("canceled") == "T":
        return []

    # 결제일시: paid_date 우선, 없으면 order_date
    paid = order.get("paid_date") or order.get("order_date", "")
    # ISO 8601 → "2026-01-19 23:41:59" 포맷으로 정규화
    if paid:
        paid = paid.replace("T", " ").split("+")[0].split(".")[0]

    # 주문상태: 엑셀 export와 맞추기 위해 "거래종료"로 고정
    # (취소는 위에서 걸러짐, 나머지는 모두 "거래종료"로 간주)
    status_text = "거래종료"

    amount = order.get("payment_amount") or order.get("actual_payment_amount") or 0
    try:
        amount = int(float(amount))
    except (ValueError, TypeError):
        amount = 0

    # 휴대전화: buyer 또는 billing_name 측에서 찾기
    phone = (
        order.get("buyer_cellphone")
        or order.get("billing_name_cellphone")
        or order.get("orderer_mobile")
        or order.get("mobile")
        or ""
    )
    # receivers에서도 시도 (embed된 경우)
    if not phone:
        receivers = order.get("receivers") or []
        if receivers:
            phone = receivers[0].get("cellphone", "") or ""

    items = order.get("items") or []
    n = max(len(items), 1)  # 아이템 정보 없어도 최소 1행

    row = [
        order.get("order_id", ""),
        paid,
        status_text,
        amount,
        phone,
    ]
    return [row] * n


def sync_cafe24(spreadsheet, days: int = BACKFILL_DAYS) -> int:
    ws = _find_tab(spreadsheet, CAFE24_HEADER_FIRST, CAFE24_HEADER_SECOND)
    if ws is None:
        raise RuntimeError("카페24 원본 탭을 찾지 못했습니다 (헤더 불일치)")
    _log(f"카페24 탭: {ws.title}")

    # 1) API에서 최근 days일 주문 pull
    orders = cafe24_client.fetch_orders(days_back=days + 1)
    _log(f"  카페24 API 주문 {len(orders)}건 수신")

    # 2) 5컬럼 행으로 변환
    new_rows: list[list] = []
    for o in orders:
        new_rows.extend(cafe24_order_to_rows(o))
    _log(f"  변환된 행: {len(new_rows)}")

    # 3) 기존 시트에서 "최근 days일 내 결제일" 행 위치 찾기
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    all_rows = ws.get_all_values()
    # 1행은 헤더
    keep: list[list] = [all_rows[0]] if all_rows else []
    delete_count = 0
    for r in all_rows[1:]:
        if len(r) < 2 or not r[1]:
            keep.append(r)
            continue
        # 결제일 비교 (문자열 비교로 OK — YYYY-MM-DD 포맷)
        if r[1] >= cutoff:
            delete_count += 1
            continue
        keep.append(r)
    _log(f"  {cutoff} 이후 기존 행 제거: {delete_count}")

    # 4) 새 행 추가
    keep.extend(new_rows)

    # 5) 시트 전체 덮어쓰기
    ws.clear()
    if keep:
        ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    _log(f"  최종 카페24 시트 행 수: {len(keep)-1}")
    return len(new_rows)


# ============================================================
# 스마트스토어
# ============================================================

# 46컬럼 헤더 순서 (시트와 동일)
SS_COLUMNS = [
    "상품주문번호", "주문번호", "구매확정일", "판매채널", "주문상태", "배송속성",
    "풀필먼트사(주문 기준)", "구매자명", "구매자ID", "수취인명", "발송처리일",
    "배송방법", "택배사", "송장번호", "배송완료일", "상품번호", "상품명", "상품종류",
    "반품안심케어", "멤버십N배송", "옵션정보", "옵션관리코드", "수량", "상품가격",
    "옵션가격", "최종 상품별 할인액", "최초 상품별 할인액", "판매자 부담 할인액",
    "최초 상품별 총 주문금액", "최종 상품별 총 주문금액", "판매자 상품코드",
    "판매자 내부코드1", "판매자 내부코드2", "배송비 묶음번호", "배송비 형태",
    "배송비 유형", "배송비 합계", "제주/도서 추가배송비", "배송비 할인액",
    "결제일", "결제수단", "결제위치", "네이버페이 주문관리 수수료",
    "매출연동 수수료", "정산예정금액", "판매옵션정보",
]


def _iso_to_sheet(dt_str: str) -> str:
    """ISO → 'YYYY-MM-DD HH:MM' 포맷."""
    if not dt_str:
        return ""
    s = dt_str.replace("T", " ").split("+")[0].split(".")[0]
    # 초 부분 제거
    parts = s.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return s


SS_STATUS_LABEL = {
    "PAYED": "결제완료",
    "DISPATCHED": "발송처리",
    "DELIVERING": "배송중",
    "DELIVERED": "배송완료",
    "PURCHASE_DECIDED": "구매확정",
    "EXCHANGED": "교환",
    "CANCELED": "취소",
    "RETURNED": "반품",
    "CANCELED_BY_NOPAYMENT": "미결제취소",
}


def _ss_wrap_to_row(wrap: dict) -> list | None:
    """SS API wrap → 46컬럼 행.

    구매확정·결제완료·발송·배송 상태 모두 포함 (취소/반품/미결제는 제외).
    분석은 주문상태 컬럼으로 필터해서 사용.
    """
    po = wrap.get("productOrder", {}) or {}
    order = wrap.get("order", {}) or {}
    delivery = wrap.get("delivery", {}) or {}

    status = po.get("productOrderStatus", "")
    # 매출로 잡히는 유효 상태만 포함 (취소/반품/미결제 제외)
    if status not in ("PAYED", "DISPATCHED", "DELIVERING", "DELIVERED", "PURCHASE_DECIDED", "EXCHANGED"):
        return None
    status_label = SS_STATUS_LABEL.get(status, status)

    def _won(v):
        try:
            return f"₩{int(float(v)):,}" if v not in (None, "") else ""
        except (ValueError, TypeError):
            return ""

    buyer_name = order.get("ordererName", "")
    buyer_id = order.get("ordererId", "") or po.get("buyerId", "")
    recipient_name = po.get("shippingAddress", {}).get("name", "") if isinstance(po.get("shippingAddress"), dict) else ""

    row = [
        po.get("productOrderId", ""),                    # 상품주문번호
        po.get("orderId", "") or order.get("orderId", ""), # 주문번호
        _iso_to_sheet(po.get("decisionDate", "") or po.get("purchaseDecisionDate", "")),  # 구매확정일 (구매확정 상태만 채워짐)
        "스마트스토어",                                    # 판매채널
        status_label,                                       # 주문상태 (결제완료/발송처리/구매확정/...)
        po.get("shippingAttribute", "") or "",            # 배송속성
        "",                                                # 풀필먼트사
        buyer_name,                                        # 구매자명
        buyer_id,                                          # 구매자ID
        recipient_name,                                    # 수취인명
        _iso_to_sheet(delivery.get("sendDate", "")),       # 발송처리일
        "택배,등기,소포",                                   # 배송방법
        delivery.get("deliveryCompany", "") or "로젠택배",  # 택배사
        delivery.get("trackingNumber", ""),                # 송장번호
        _iso_to_sheet(delivery.get("deliveredDate", "")),  # 배송완료일
        str(po.get("productId", "")),                      # 상품번호
        po.get("productName", ""),                         # 상품명
        po.get("productClass", "") or "조합형옵션상품",      # 상품종류
        "비대상",                                          # 반품안심케어
        "비대상",                                          # 멤버십N배송
        po.get("productOption", ""),                       # 옵션정보
        "",                                                # 옵션관리코드
        po.get("quantity", 0),                             # 수량
        _won(po.get("unitPrice", 0) or po.get("productPrice", 0)),  # 상품가격
        _won(po.get("optionPrice", 0)),                    # 옵션가격
        _won(po.get("productDiscountAmount", 0)),          # 최종 상품별 할인액
        _won(po.get("initialProductDiscountAmount", 0) or po.get("productDiscountAmount", 0)),  # 최초 상품별 할인액
        _won(po.get("sellerBurdenDiscountAmount", 0)),     # 판매자 부담 할인액
        _won(po.get("initialPaymentAmount", 0) or po.get("totalPaymentAmount", 0)),  # 최초 상품별 총 주문금액
        _won(po.get("totalPaymentAmount", 0)),             # 최종 상품별 총 주문금액
        po.get("sellerProductCode", ""),                   # 판매자 상품코드
        "", "",                                             # 내부코드1, 2
        po.get("deliveryFeeGroupId", "") or "",            # 배송비 묶음번호
        "선결제",                                          # 배송비 형태
        "조건부무료",                                       # 배송비 유형
        _won(po.get("deliveryFeeAmount", 0)),              # 배송비 합계
        _won(po.get("remoteAreaDeliveryFee", 0)),          # 제주/도서 추가배송비
        _won(po.get("deliveryFeeDiscountAmount", 0)),      # 배송비 할인액
        _iso_to_sheet(order.get("paymentDate", "")),       # 결제일 (order에 위치)
        order.get("paymentMeans", "") or "",               # 결제수단 (order에 위치)
        order.get("payLocationType", "") or "",            # 결제위치 (order.payLocationType)
        _won(po.get("commissionRatePayCost", 0) or 0),     # 네이버페이 주문관리 수수료
        _won(po.get("commissionFee", 0) or po.get("salesChannelPayCommission", 0) or 0),  # 매출연동 수수료
        _won(po.get("expectedSettlementAmount", 0)),       # 정산예정금액
        "",                                                # 판매옵션정보
    ]
    # 46개 보장
    assert len(row) == len(SS_COLUMNS), f"SS row 컬럼 수 불일치: {len(row)} vs {len(SS_COLUMNS)}"
    return row


def sync_smartstore(spreadsheet, days: int = BACKFILL_DAYS) -> int:
    """스마트스토어 sync — 결제·발송·배송·구매확정 상태 모두 포함.

    24시간 윈도우 한계 우회를 위해 1일씩 잘라 호출하고 productOrderId로 dedupe.
    cutoff는 구매확정일(있으면) 또는 결제일(없으면) 기준으로 비교.
    """
    import time as _time
    ws = _find_tab(spreadsheet, SS_HEADER_FIRST)
    if ws is None:
        raise RuntimeError("스마트스토어 원본 탭을 찾지 못했습니다")
    _log(f"스마트스토어 탭: {ws.title}")

    # 구매확정 + 결제완료 + 발송처리 + 배송중 + 배송완료 모두 수집
    # (CANCELED/RETURNED는 자연스럽게 제외)
    statuses = ["PURCHASE_DECIDED", "PAYED", "DISPATCHED", "DELIVERING", "DELIVERED"]
    token = naver_client.get_access_token()
    seen: dict = {}

    for status in statuses:
        # 1일씩 잘라서 호출 (한 번에 24h 한계 + RATE_LIMIT 회피)
        for d in range(1, days + 1):
            try:
                changes = naver_client.get_changed_product_orders(
                    token, status, hours_back=d * 24
                )
            except Exception as e:
                msg = str(e)
                if "RATE_LIMIT" in msg or "429" in msg:
                    _time.sleep(5)
                    try:
                        changes = naver_client.get_changed_product_orders(
                            token, status, hours_back=d * 24
                        )
                    except Exception:
                        continue
                else:
                    continue
            for c in changes:
                pid = c.get("productOrderId")
                if pid:
                    seen[pid] = c
            _time.sleep(1.2)
        _log(f"  status={status} 누적 unique: {len(seen)}건")

    # 상세 조회 (300개씩 배치)
    ids = list(seen.keys())
    orders = naver_client.get_order_details(token, ids)
    _log(f"  SS API 상세 {len(orders)}건 수신 (최근 {days}일, 5개 상태)")

    new_rows: list[list] = []
    for w in orders:
        row = _ss_wrap_to_row(w)
        if row is not None:
            new_rows.append(row)
    _log(f"  변환된 행: {len(new_rows)}")

    # cutoff: 구매확정일(col 2) 또는 결제일(col 39) 둘 중 하나라도 cutoff 이후면 제거
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    all_rows = ws.get_all_values()
    keep: list[list] = [all_rows[0]] if all_rows else []
    delete_count = 0
    for r in all_rows[1:]:
        decision = r[2][:10] if len(r) > 2 and r[2] else ""
        payment = r[39][:10] if len(r) > 39 and r[39] else ""
        latest = max(decision, payment)
        if latest and latest >= cutoff:
            delete_count += 1
            continue
        keep.append(r)
    _log(f"  {cutoff} 이후 기존 행 제거: {delete_count}")

    keep.extend(new_rows)

    ws.clear()
    if keep:
        ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    _log(f"  최종 SS 시트 행 수: {len(keep)-1}")
    return len(new_rows)


# ============================================================
# main
# ============================================================

def run() -> dict:
    _log("=== 재구매 시트 이관 시작 ===")
    ss = _open_sheet()
    _log(f"스프레드시트: {ss.title}")

    result = {"cafe24": 0, "smartstore": 0, "errors": []}

    try:
        result["cafe24"] = sync_cafe24(ss)
    except Exception as e:
        _log(f"카페24 실패: {e}")
        result["errors"].append(f"cafe24: {e}")

    try:
        result["smartstore"] = sync_smartstore(ss)
    except Exception as e:
        _log(f"스마트스토어 실패: {e}")
        result["errors"].append(f"smartstore: {e}")

    _log(f"=== 완료: 카페24 {result['cafe24']}행, SS {result['smartstore']}행 ===")
    return result


if __name__ == "__main__":
    import json
    try:
        r = run()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if not r["errors"] else 1)
    except Exception as e:
        _log(f"치명적 오류: {e}")
        sys.exit(2)
