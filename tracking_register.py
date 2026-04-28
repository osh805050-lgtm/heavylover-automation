"""송장 자동 등록 모듈

1. PlusCL API에서 출고 완료된 송장 조회
2. 텔레그램으로 사장님에게 알림 + 승인 요청
3. /done 받으면 카페24 + 스마트스토어에 송장 자동 등록
4. 완료 알림

실행 주기: 평일 13:00 (cron)
"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# Windows cp949 콘솔 대응
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import cafe24_client
import naver_client
import telegram_client

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


def register_tracking_cafe24(order_id, item_code, tracking_no, carrier_code):
    """카페24에 송장번호 등록 (배송중 전환)

    POST /api/v2/admin/orders/{order_id}/shipments
    """
    body = {
        "shop_no": 1,
        "request": {
            "order_item_code": [item_code],
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
