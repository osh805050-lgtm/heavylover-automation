"""송장 자동 등록 모듈

텔레그램 /tracking 명령 → 바탕화면 더다 엑셀 자동 감지 → 카페24/SS 송장 등록

실행 주기: Vultr cron 5분마다 /tracking 명령 폴링
"""

import glob
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# Windows cp949 콘솔 대응
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import cafe24_client
import coupang_client
import naver_client
import telegram_client

# 더다 송장 엑셀 OneDrive 경로 (rclone remote 기준) — 바탕화면
ONEDRIVE_TRACKING_DIR = os.getenv(
    "ONEDRIVE_TRACKING_DIR",
    "heavylover_onedrive:바탕 화면/",
)
# 서버 로컬 다운로드 위치
LOCAL_TRACKING_DIR = Path(os.getenv("LOCAL_TRACKING_DIR", "/tmp/tracking_excel"))

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH, override=True)

# PlusCL API 설정
PLUSCL_BASE = "https://service.pluscl.com"

# 택배사 코드 매핑 - 헤비로버는 로젠택배 전용
# 이 몰(musclecipe001)에서 로젠택배의 카페24 코드는 0004 (테스트 확인됨)
# PlusCL 택배사 코드는 실제 응답에서 확인 필요 (예상: D005)

# 카페24 shipping_company_code (이 몰 기준)
CAFE24_LOGEN = "0004"

# 네이버 deliveryCompanyCode
NAVER_LOGEN = "KGB"  # 로젠택배 (네이버 시스템에선 KGB 코드)

def find_today_excel():
    """OneDrive 바탕화면에서 오늘 날짜 송장 엑셀만 다운로드 후 경로 반환.

    오늘 날짜 파일이 없으면 None 반환 (이전 날짜 fallback 없음 — 잘못된 송장번호 등록 차단).
    """
    import subprocess
    LOCAL_TRACKING_DIR.mkdir(parents=True, exist_ok=True)

    # rclone으로 최신 파일 동기화
    r = subprocess.run(
        ["rclone", "copy", ONEDRIVE_TRACKING_DIR, str(LOCAL_TRACKING_DIR),
         "--include", "일반_*.xls*", "--max-depth", "1", "--transfers=4"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"rclone 오류: {r.stderr[:200]}")

    # 오늘 날짜 파일만 찾음 — 없으면 None (이전 날짜 fallback 제거)
    today = datetime.now().strftime("%Y%m%d")
    today_files = sorted(LOCAL_TRACKING_DIR.glob(f"일반_*{today}*.xls*"))
    return today_files[-1] if today_files else None


def read_tracking_excel(path: Path):
    """더다 송장 엑셀 읽기. 카페24/SS/쿠팡 분류 + 전화번호 기준 구매자 수 반환.

    분류 기준:
      - 카페24: 주문번호에 하이픈 포함 (YYYYMMDD-NNNNNNN)
      - 스마트스토어: 16자리 숫자, "20"으로 시작
      - 쿠팡: 그 외 (13자리 숫자 등)

    Returns:
        dict: {
            "cafe24": [(order_id, item_code, tracking_no)],
            "naver": [(product_order_id, tracking_no)],
            "coupang": [(order_id, tracking_no)],
            "cafe24_buyers": int,
            "naver_buyers": int,
            "coupang_buyers": int,
            "filename": str,
        }
    """
    # xls는 xlrd로 cp949 읽기, xlsx는 openpyxl
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path), encoding_override="cp949")
        ws = wb.sheet_by_index(0)
        headers = ws.row_values(0)
        rows = [ws.row_values(i) for i in range(1, ws.nrows)]
        df = pd.DataFrame(rows, columns=headers)
    else:
        df = pd.read_excel(path)

    def _to_str(val):
        """숫자형 셀값을 문자열로 변환 (과학적 표기·부동소수점 오차 방지)"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        s = str(val).strip()
        if not s or s == "nan":
            return ""
        # xlrd가 과학적 표기 문자열로 반환하는 경우 (예: 2.02604287400767E15)
        # Decimal로 파싱해야 부동소수점 오차 없이 정확한 정수 복원 가능
        if "E" in s.upper() and "." in s:
            try:
                from decimal import Decimal
                return str(int(Decimal(s)))
            except Exception:
                pass
        # 일반 숫자 (float → int)
        try:
            return str(int(float(s)))
        except Exception:
            return s

    df["송장번호"] = df["송장번호"].apply(_to_str)
    df["주문번호"] = df["주문번호"].apply(_to_str)

    cafe24_rows = []
    naver_rows = []
    coupang_rows = []
    cafe24_phones = set()
    naver_phones = set()
    coupang_phones = set()

    for _, row in df.iterrows():
        order_no = _to_str(row.get("주문번호", ""))
        tracking = _to_str(row.get("송장번호", ""))
        phone = str(row.get("수취인 휴대전화", "") or row.get("수취인 전화", "")).strip()

        if not order_no or not tracking or tracking == "nan":
            continue

        # 카페24: YYYYMMDD-NNNNNNN 형식 (하이픈 포함)
        if "-" in order_no:
            item_code = str(row.get("주문 상품코드", "")).strip()
            cafe24_rows.append((order_no, item_code, tracking))
            if phone:
                cafe24_phones.add(phone)
        elif len(order_no) == 16 and order_no.startswith("20"):
            # 스마트스토어: 16자리, "20"으로 시작
            naver_rows.append((order_no, tracking))
            if phone:
                naver_phones.add(phone)
        else:
            # 쿠팡: 그 외 (13자리 등)
            coupang_rows.append((order_no, tracking))
            if phone:
                coupang_phones.add(phone)

    return {
        "cafe24": cafe24_rows,
        "naver": naver_rows,
        "coupang": coupang_rows,
        "cafe24_buyers": len(cafe24_phones),
        "naver_buyers": len(naver_phones),
        "coupang_buyers": len(coupang_phones),
        "filename": path.name,
    }


def run_from_excel():
    """엑셀 기반 송장 등록 — 발주 자동화(/tracking)에서 호출됨"""
    now = datetime.now()
    print(f"=== 엑셀 송장 등록 시작 ({now:%Y-%m-%d %H:%M:%S}) ===\n")

    # 1) 엑셀 파일 찾기 (오늘 날짜만 — 이전 날짜 fallback 없음)
    excel_path = find_today_excel()
    if not excel_path:
        today = datetime.now().strftime("%Y%m%d")
        telegram_client.send_message(
            f"⚠️ 오늘({today}) 송장 엑셀을 찾을 수 없습니다.\n"
            f"OneDrive 바탕화면에 '일반_{today}.xls' 파일을 올린 후\n"
            f"다음 11시 자동화에서 다시 시도해주세요.",
            channel="ops",
        )
        return

    print(f"  파일: {excel_path.name}")

    # 2) 엑셀 파싱
    try:
        data = read_tracking_excel(excel_path)
    except Exception as e:
        telegram_client.send_message(f"⚠️ 엑셀 읽기 실패: {e}", channel="ops")
        return

    cafe24_items = data["cafe24"]
    naver_items = data["naver"]
    coupang_items = data["coupang"]
    total_buyers = data["cafe24_buyers"] + data["naver_buyers"] + data["coupang_buyers"]

    if not cafe24_items and not naver_items and not coupang_items:
        telegram_client.send_message("⚠️ 등록할 송장이 없습니다.", channel="ops")
        return

    # 3) 즉시 등록 시작 (재확인 단계 없음 — 이미 /tracking 받은 상태)
    telegram_client.send_message(
        f"📦 송장 등록 시작\n"
        f"파일: {data['filename']}\n"
        f"카페24 {data['cafe24_buyers']}명 + SS {data['naver_buyers']}명 + 쿠팡 {data['coupang_buyers']}명 = 총 {total_buyers}명",
        channel="ops",
    )

    # 4) 송장 등록
    print("[등록] 카페24 + 스마트스토어 송장 등록 중...")
    cafe24_success, cafe24_fail = 0, []
    naver_success, naver_fail = 0, []

    # 카페24: 주문번호 중복 제거 후 API로 order_item_code 조회
    seen_cafe24 = {}
    for order_id, _, tracking in cafe24_items:
        if order_id not in seen_cafe24:
            seen_cafe24[order_id] = tracking

    for order_id, tracking in seen_cafe24.items():
        try:
            item_codes = cafe24_client.get_order_item_codes(order_id)
            if not item_codes:
                cafe24_fail.append(f"{order_id}: order_item_code 조회 실패")
                continue
            r = register_tracking_cafe24(order_id, item_codes, tracking, CAFE24_LOGEN)
            if r.status_code in (200, 201):
                cafe24_success += 1
            elif r.status_code == 422 and "cannot change" in r.text:
                cafe24_success += 1  # 이미 배송중 등록된 건 — 성공으로 처리
            else:
                cafe24_fail.append(f"{order_id}: {r.text[:80]}")
        except Exception as e:
            cafe24_fail.append(f"{order_id}: {e}")

    # SS: 엑셀 주문번호 부동소수점 손실 보정 — API 현재 발송대기 주문과 앞 15자리 매칭
    actual_naver_orders = naver_client.orders_pending_dispatch(days_back=7)
    actual_ids = {
        o.get("productOrder", {}).get("productOrderId", ""): True
        for o in actual_naver_orders
    }

    def _fix_naver_id(excel_id):
        """엑셀 주문번호(마지막 자리 소실)를 실제 SS 주문번호로 보정."""
        if excel_id in actual_ids:
            return excel_id
        prefix = excel_id[:15]
        for real_id in actual_ids:
            if real_id.startswith(prefix):
                return real_id
        return excel_id  # 보정 실패 시 원본 유지

    seen_naver = {}
    for product_order_id, tracking in naver_items:
        fixed_id = _fix_naver_id(product_order_id)
        if fixed_id not in seen_naver:
            seen_naver[fixed_id] = tracking

    import time as _time
    for product_order_id, tracking in seen_naver.items():
        for attempt in range(3):  # RATE_LIMIT 시 최대 3회 재시도
            try:
                r = register_tracking_naver(product_order_id, tracking, NAVER_LOGEN)
                if r.status_code == 200:
                    result = r.json().get("data", {})
                    if result.get("successProductOrderIds"):
                        naver_success += 1
                        break
                    else:
                        fail_info = result.get("failProductOrderInfos", [{}])
                        msg = fail_info[0].get("message", "fail") if fail_info else "fail"
                        if "RATE_LIMIT" in str(r.text) and attempt < 2:
                            _time.sleep(3)
                            continue
                        naver_fail.append(f"{product_order_id}: {msg}")
                        break
                elif "RATE_LIMIT" in r.text and attempt < 2:
                    _time.sleep(3)
                    continue
                else:
                    naver_fail.append(f"{product_order_id}: {r.text[:80]}")
                    break
            except Exception as e:
                naver_fail.append(f"{product_order_id}: {e}")
                break
        _time.sleep(0.5)  # 호출 간격

    # 쿠팡: orderId 중복 제거 후 vendorItemId 조회 → 등록
    coupang_success, coupang_fail = 0, []
    seen_coupang = {}
    for order_id, tracking in coupang_items:
        if order_id not in seen_coupang:
            seen_coupang[order_id] = tracking

    if seen_coupang:
        print("[쿠팡] shipmentBoxId/vendorItemId 조회 중 (fetch_orders)...")
        for order_id, tracking in seen_coupang.items():
            try:
                info = coupang_client.get_order_shipping_info(order_id)
                if not info or not info["vendorItemIds"]:
                    coupang_fail.append(f"{order_id}: 주문 정보 조회 실패 (INSTRUCT 상태 아닐 수 있음)")
                    continue
                r = coupang_client.register_tracking(
                    order_id, info["shipmentBoxId"], info["vendorItemIds"], tracking
                )
                if r.status_code in (200, 201):
                    coupang_success += 1
                else:
                    coupang_fail.append(f"{order_id}: {r.text[:100]}")
            except Exception as e:
                coupang_fail.append(f"{order_id}: {e}")

    # 5) 완료 알림
    result_msg = (
        f"✅ 송장 등록 완료\n\n"
        f"카페24: {cafe24_success}/{len(seen_cafe24)}건 성공\n"
        f"스마트스토어: {naver_success}/{len(seen_naver)}건 성공\n"
        f"쿠팡: {coupang_success}/{len(seen_coupang)}건 성공"
    )
    if cafe24_fail:
        result_msg += "\n\n카페24 실패:\n" + "\n".join(f"  - {e}" for e in cafe24_fail[:5])
    if naver_fail:
        result_msg += "\n\n스마트스토어 실패:\n" + "\n".join(f"  - {e}" for e in naver_fail[:5])
    if coupang_fail:
        result_msg += "\n\n쿠팡 실패:\n" + "\n".join(f"  - {e}" for e in coupang_fail[:5])

    telegram_client.send_message(result_msg, channel="ops")
    print(result_msg)


def pluscl_to_cafe24(pluscl_code):
    """PlusCL tran_comp_code를 카페24 shipping_company_code로 변환.
    헤비로버는 로젠만 쓰므로 전부 로젠(0004)으로 매핑."""
    return CAFE24_LOGEN

def pluscl_to_naver(pluscl_code):
    """PlusCL tran_comp_code를 네이버 deliveryCompanyCode로 변환."""
    return NAVER_LOGEN

# 호환성 유지
CARRIER_MAP_CAFE24 = {"DEFAULT": CAFE24_LOGEN}
CARRIER_MAP_NAVER = {"DEFAULT": NAVER_LOGEN}


def _get_pluscl_config():
    load_dotenv(ENV_PATH, override=True)
    return {
        "auth_key": os.getenv("PLUSCL_AUTH_KEY"),
        "company_code": os.getenv("PLUSCL_COMPANY_CODE"),
        "warehouse_code": os.getenv("PLUSCL_WAREHOUSE_CODE"),
        "seller_code": os.getenv("PLUSCL_SELLER_CODE"),
        "user_id": os.getenv("PLUSCL_USER_ID"),
    }


def fetch_pluscl_shipments(hours_back=24):
    """PlusCL에서 최근 출고 완료 건 조회 (주문 출고내역)

    Returns:
        list[dict]: 출고 완료된 주문 리스트
            각 항목: {ord_no1, tran_comp_code, invoice_no, ord_comp_code, ...}
    """
    cfg = _get_pluscl_config()
    if not cfg["auth_key"]:
        print("⚠️ PLUSCL_AUTH_KEY 환경변수 미설정 — PlusCL 연동 불가")
        return []

    now = datetime.now()
    # 조회 범위: hours_back 시간 전부터 지금까지
    end = now
    start = datetime.fromtimestamp(now.timestamp() - hours_back * 3600)

    body = {
        "company_code": cfg["company_code"],
        "user_id": cfg["user_id"],
        "warehouse_code": cfg["warehouse_code"],
        "warehouse_type_code": "0000",
        "seller_code": cfg["seller_code"],
        "job_type": "search",
        "type": "doc",
        "IsOld": "Y",
        "data": {
            "begin_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "warehouse_type_code": "",
            "stock_no": "",
            "stock_kind": "",
        },
    }

    # 출고서 조회 API
    r = requests.post(
        f"{PLUSCL_BASE}/open/item_out",
        headers={"auth_key": cfg["auth_key"], "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if r.status_code != 200:
        print(f"PlusCL 조회 실패: {r.status_code} - {r.text[:200]}")
        return []

    data = r.json().get("data", [])
    # invoice_no가 있는 건만 (= 출고 완료)
    return [d for d in data if d.get("invoice_no")]


def register_tracking_cafe24(order_id, item_codes, tracking_no, carrier_code):
    """카페24에 송장번호 등록 (배송중 전환)

    item_codes: list[str] — API 조회로 얻은 order_item_code 목록
    """
    if isinstance(item_codes, str):
        item_codes = [item_codes]
    body = {
        "shop_no": 1,
        "request": {
            "order_item_code": item_codes,
            "tracking_no": tracking_no,
            "shipping_company_code": carrier_code,
            "status": "shipping",
        },
    }
    return cafe24_client._api_post(f"/api/v2/admin/orders/{order_id}/shipments", body)


def register_tracking_naver(product_order_id, tracking_no, carrier_code):
    """네이버에 송장번호 등록 (배송중 전환)

    POST /pay-order/seller/product-orders/dispatch
    """
    token = naver_client.get_access_token()
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    dispatch_date = datetime.now(kst).isoformat(timespec="milliseconds")

    body = {
        "dispatchProductOrders": [{
            "productOrderId": product_order_id,
            "deliveryMethod": "DELIVERY",
            "deliveryCompanyCode": carrier_code,
            "trackingNumber": tracking_no,
            "dispatchDate": dispatch_date,
        }]
    }
    r = requests.post(
        f"{naver_client.API_BASE}/v1/pay-order/seller/product-orders/dispatch",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        proxies=naver_client._get_proxies(),
    )
    return r


def run():
    print(f"=== 송장 자동 등록 시작 ({datetime.now():%Y-%m-%d %H:%M:%S}) ===\n")

    # 1) PlusCL에서 출고 완료 건 조회
    print("[1/4] PlusCL 출고 완료 조회...")
    shipments = fetch_pluscl_shipments(hours_back=24)
    print(f"  - 출고 완료: {len(shipments)}건")

    if not shipments:
        print("처리할 송장 없음. 종료.")
        return

    # 2) 출처별로 분류 (카페24 vs 스마트스토어)
    cafe24_items = []
    naver_items = []
    for s in shipments:
        ord_no1 = s.get("ord_no1", "")
        carrier = s.get("tran_comp_code", "")
        invoice = s.get("invoice_no", "")
        # 주문번호 형식으로 출처 판별
        # 카페24: YYYYMMDD-NNNNNNN 형식
        # 스마트스토어: 16자리 숫자
        if "-" in ord_no1:
            cafe24_items.append(s)
        else:
            naver_items.append(s)

    # 3) 텔레그램 승인 요청
    print("[2/4] 텔레그램 승인 요청 중...")
    msg = (
        f"📦 송장 도착 알림 ({datetime.now():%H:%M})\n\n"
        f"PlusCL 출고 완료: {len(shipments)}건\n"
        f"- 카페24: {len(cafe24_items)}건\n"
        f"- 스마트스토어: {len(naver_items)}건\n\n"
        f"/done → 카페24/스마트스토어 송장 자동 등록\n"
        f"/cancel → 오늘 등록 취소 (수동 처리)"
    )
    telegram_client.send_message(msg, channel="ops")

    print("[3/4] 응답 대기 중 (최대 8시간)...")
    cmd = telegram_client.wait_for_command(["/done", "/cancel"], timeout_seconds=28800, channel="ops")
    if cmd == "/cancel":
        telegram_client.send_message("❌ 송장 등록 취소됨. 수동으로 처리해주세요.", channel="ops")
        return
    if cmd is None:
        telegram_client.send_message("⏰ 응답 대기 타임아웃. 송장 등록 건너뜀.", channel="ops")
        return
    print(f"  - 승인 받음 ({cmd})")

    # 4) 송장 등록 실행
    print("[4/4] 송장 등록 중...")
    cafe24_success = 0
    cafe24_fail = []
    naver_success = 0
    naver_fail = []

    for s in cafe24_items:
        order_id = s.get("ord_no1")
        item_code = s.get("ord_item_code") or f"{order_id}-{s.get('item_seq',1):02d}"
        tracking = s.get("invoice_no")
        pluscl_carrier = s.get("tran_comp_code")
        carrier_code = pluscl_to_cafe24(pluscl_carrier)
        try:
            r = register_tracking_cafe24(order_id, item_code, tracking, carrier_code)
            if r.status_code in (200, 201):
                cafe24_success += 1
            else:
                cafe24_fail.append(f"{order_id}: {r.text[:100]}")
        except Exception as e:
            cafe24_fail.append(f"{order_id}: {e}")

    for s in naver_items:
        product_order_id = s.get("ord_no1")
        tracking = s.get("invoice_no")
        pluscl_carrier = s.get("tran_comp_code")
        carrier_code = pluscl_to_naver(pluscl_carrier)
        try:
            r = register_tracking_naver(product_order_id, tracking, carrier_code)
            if r.status_code == 200:
                result = r.json().get("data", {})
                if result.get("successProductOrderIds"):
                    naver_success += 1
                else:
                    naver_fail.append(f"{product_order_id}: {result.get('failProductOrderInfos', [{}])[0].get('message','fail')}")
            else:
                naver_fail.append(f"{product_order_id}: {r.text[:100]}")
        except Exception as e:
            naver_fail.append(f"{product_order_id}: {e}")

    # 완료 알림
    result_msg = (
        f"✅ 송장 등록 완료\n\n"
        f"카페24: {cafe24_success}/{len(cafe24_items)}건 성공"
    )
    if cafe24_fail:
        result_msg += "\n실패:\n" + "\n".join(f"  - {e}" for e in cafe24_fail[:5])
    result_msg += f"\n\n스마트스토어: {naver_success}/{len(naver_items)}건 성공"
    if naver_fail:
        result_msg += "\n실패:\n" + "\n".join(f"  - {e}" for e in naver_fail[:5])

    telegram_client.send_message(result_msg, channel="ops")
    print(result_msg)


if __name__ == "__main__":
    run()
