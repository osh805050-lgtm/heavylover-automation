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


def _atomic_replace_worksheet(
    spreadsheet,
    prod_tab_name: str,
    header: list,
    rows: list[list],
    log_fn=None,
) -> None:
    """프로덕션 워크시트를 staging→rename 패턴으로 원자적 교체.

    동작 순서:
      1) `{prod}__staging` 탭 확보 (기존 있으면 clear, 없으면 add).
      2) staging 에 [header] + rows 한 번에 write.
      3) staging 검증: 첫 행 == header AND 데이터 행 수 == len(rows).
         불일치 시 RuntimeError → 프로덕션 탭은 손대지 않음.
      4) rename swap:
            prod        → `{prod}__prev`
            staging     → prod
            `{prod}__prev` 삭제
         어느 단계 실패 시 raise (cron 빨간불).

    실패 시 보장:
      - 2~3 실패: 프로덕션 탭 그대로. staging 만 일관성 깨진 상태.
      - 4 중 prod→prev 실패: 프로덕션 그대로.
      - 4 중 staging→prod 실패: 프로덕션은 `__prev` 로 살아있음(수동 복구 가능).
      - 4 중 prev 삭제 실패: 데이터는 정상, `__prev` 잔재 다음 실행 시 흡수.
    """
    log = log_fn if callable(log_fn) else _log
    staging_name = f"{prod_tab_name}__staging"
    prev_name = f"{prod_tab_name}__prev"

    # 0) 스프레드시트 워크시트 핸들 일괄 조회 (리스트 1회 fetch)
    worksheets = {ws.title: ws for ws in spreadsheet.worksheets()}

    if prod_tab_name not in worksheets:
        raise RuntimeError(f"프로덕션 탭 '{prod_tab_name}' 없음 — atomic swap 불가")
    prod_ws = worksheets[prod_tab_name]

    # 잔존 __prev 가 있으면 정리 (이전 실행 중간 실패 흔적)
    if prev_name in worksheets:
        try:
            spreadsheet.del_worksheet(worksheets[prev_name])
            log(f"  ↳ 잔존 '{prev_name}' 정리")
        except Exception as e:
            log(f"  ⚠️ 잔존 '{prev_name}' 삭제 실패: {e} (계속 진행)")

    # 1) staging 확보
    payload = ([header] + rows) if rows else [header]
    needed_rows = max(len(payload), 100)
    needed_cols = max(len(header), 26)

    if staging_name in worksheets:
        staging_ws = worksheets[staging_name]
        try:
            staging_ws.clear()
        except Exception as e:
            raise RuntimeError(f"staging '{staging_name}' clear 실패: {e}") from e
        # row/col 수 확장이 필요하면 resize
        try:
            if staging_ws.row_count < needed_rows or staging_ws.col_count < needed_cols:
                staging_ws.resize(rows=needed_rows, cols=needed_cols)
        except Exception:
            pass
    else:
        staging_ws = spreadsheet.add_worksheet(
            title=staging_name, rows=needed_rows, cols=needed_cols
        )

    # 2) staging write
    staging_ws.update(values=payload, range_name="A1", value_input_option="USER_ENTERED")

    # 3) 검증: 헤더 일치 + 데이터 행 수 일치
    written = staging_ws.get_all_values()
    if not written:
        raise RuntimeError(f"staging '{staging_name}' write 직후 빈 값 — abort")
    written_header = written[0]
    # gspread 가 trailing 빈 셀을 잘라내는 경우가 있으니 prefix 비교
    if written_header[: len(header)] != list(header):
        raise RuntimeError(
            f"staging 헤더 불일치: 기대={header[:3]}... / 실제={written_header[:3]}..."
        )
    written_data_count = len(written) - 1
    if written_data_count != len(rows):
        raise RuntimeError(
            f"staging 행 수 불일치: 기대={len(rows)} / 실제={written_data_count}"
        )

    # 4) rename swap
    try:
        prod_ws.update_title(prev_name)
    except Exception as e:
        raise RuntimeError(f"prod→prev rename 실패: {e}") from e

    try:
        staging_ws.update_title(prod_tab_name)
    except Exception as rename_err:
        # H-6 fix: staging→prod rename 실패 시 prod(__prev)를 원복해 데이터 손실 방지.
        # prod 탭이 __prev 이름으로 살아있으므로 원래 이름으로 되돌린다.
        log(f"  ⚠️ staging→prod rename 실패: {rename_err} — 원복 시도")
        try:
            prod_ws.update_title(prod_tab_name)
            log(f"  ✅ '{prev_name}' → '{prod_tab_name}' 원복 성공 (데이터 보존)")
        except Exception as restore_err:
            log(f"  🚨 원복도 실패: {restore_err} — '{prev_name}' 탭을 수동으로 '{prod_tab_name}'으로 이름 변경 필요")
        raise RuntimeError(
            f"staging→prod rename 실패 ('{prev_name}' → '{prod_tab_name}' 원복 시도됨): {rename_err}"
        ) from rename_err

    try:
        spreadsheet.del_worksheet(prod_ws)  # 이제 이름이 prev_name 인 탭
    except Exception as e:
        log(f"  ⚠️ '{prev_name}' 삭제 실패: {e} (다음 실행 시 자동 정리)")

    log(f"  ✅ atomic swap 완료 ('{prod_tab_name}' ← '{staging_name}')")


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

    # 100% 할인 주문(결제금액 0원) → items[].price 합산으로 정가 대체
    # embed=items 이미 사용 중이므로 추가 API 호출 없음
    if amount == 0:
        fallback = 0
        for item in (order.get("items") or []):
            try:
                unit = int(float(item.get("product_price") or item.get("price") or 0))
                qty = int(item.get("quantity") or 1)
                fallback += unit * qty
            except (ValueError, TypeError):
                pass
        if fallback > 0:
            amount = fallback

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
    """카페24 sync — cutoff 기반 행 교체 + (주문번호, 아이템번호 기준) dedupe.

    같은 주문이 옵션·수량으로 여러 행으로 분해될 수 있으므로
    (주문번호 + 결제일시 + 실결제금액) 조합 키로 시트 내 중복 제거.
    """
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

    # 3) cutoff: 결제일시 컬럼은 "2026-04-19 18:04:28" 형식
    #   문자열 비교에서 "2026-04-19 18:04" < "2026-04-20" 이므로
    #   cutoff에 " 00:00" 같은 시간 안 붙이면 4/20 03시 행이 빠지지 않음.
    #   안전을 위해 cutoff에 " 00:00" 부착.
    cutoff_date = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    cutoff = cutoff_date + " 00:00"
    all_rows = ws.get_all_values()
    keep: list[list] = [all_rows[0]] if all_rows else []
    delete_count = 0
    for r in all_rows[1:]:
        if len(r) < 2 or not r[1]:
            keep.append(r)
            continue
        if r[1] >= cutoff:
            delete_count += 1
            continue
        keep.append(r)
    _log(f"  {cutoff} 이후 기존 행 제거: {delete_count}")

    # 4) 새 행 추가
    keep.extend(new_rows)

    # 5) (주문번호 + 결제일시 + 실결제금액) 조합 키로 시트 전체 dedupe
    #   같은 옵션·수량 분해 행은 휴대전화·금액까지 같으니 그대로 보존.
    seen = set()
    deduped = [keep[0]] if keep else []
    for r in keep[1:]:
        key = tuple(r[:5]) if len(r) >= 5 else tuple(r)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    removed_dup = len(keep) - len(deduped)
    if removed_dup > 0:
        _log(f"  완전중복 제거: {removed_dup}행")

    # 6) 시트 전체 덮어쓰기 (atomic swap: clear→update 사이 process kill 시 빈 시트 방지)
    if deduped:
        header = deduped[0]
        data_rows = deduped[1:]
    else:
        # 안전장치: dedupe 결과가 비면 최소 헤더라도 보존
        header = ws.row_values(1) or [CAFE24_HEADER_FIRST, CAFE24_HEADER_SECOND]
        data_rows = []
    _atomic_replace_worksheet(spreadsheet, ws.title, header, data_rows, log_fn=_log)
    _log(f"  최종 카페24 시트 행 수: {len(data_rows)}")
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
            skipped = 0
            for c in changes:
                pid = c.get("productOrderId")
                if pid:
                    seen[pid] = c
                else:
                    skipped += 1
            if skipped:
                _log(f"  ⚠️ productOrderId 빈 주문 {skipped}건 제외 (status={status})")
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

    # productOrderId 기준 dedupe — 신규(new_rows)가 뒤에 있으니
    # 같은 pid가 있으면 *나중 행(새 정보)*을 유지
    seen_pid = set()
    deduped = []
    if keep:
        deduped.append(keep[0])  # 헤더
    for r in reversed(keep[1:]):
        pid = r[0] if r else ""
        if not pid or pid in seen_pid:
            if pid:
                continue
        seen_pid.add(pid)
        deduped.append(r)
    # reversed 순회했으니 다시 뒤집어 시간 순 복원
    deduped = [deduped[0]] + list(reversed(deduped[1:]))
    removed_dup = len(keep) - len(deduped)
    if removed_dup > 0:
        _log(f"  productOrderId 중복 제거: {removed_dup}행")

    # atomic swap: clear→update 사이 process kill 시 빈 시트 방지
    if deduped:
        header = deduped[0]
        data_rows = deduped[1:]
    else:
        header = ws.row_values(1) or list(SS_COLUMNS)
        data_rows = []
    _atomic_replace_worksheet(spreadsheet, ws.title, header, data_rows, log_fn=_log)
    _log(f"  최종 SS 시트 행 수: {len(data_rows)}")
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
