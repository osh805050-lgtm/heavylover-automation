"""네이버 커머스 API 클라이언트 - 스마트스토어 주문 조회"""

import base64
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pandas as pd
import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
API_BASE = "https://api.commerce.naver.com/external"
KST = timezone(timedelta(hours=9))


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    return {
        "client_id": os.getenv("NAVER_CLIENT_ID"),
        "client_secret": os.getenv("NAVER_CLIENT_SECRET"),
    }


def _get_proxies():
    """네이버 API 호출용 프록시 설정 (고정 IP 경유).
    PROXY_BYPASS=1 환경변수면 프록시 사용 안 함 (서버 자체에서 실행 시).
    """
    load_dotenv(ENV_PATH, override=True)
    if os.getenv("PROXY_BYPASS") == "1":
        return None
    host = os.getenv("PROXY_HOST")
    if not host:
        return None
    user = os.getenv("PROXY_USER")
    password = os.getenv("PROXY_PASSWORD")
    port = os.getenv("PROXY_PORT", "3128")
    url = f"http://{user}:{password}@{host}:{port}"
    return {"http": url, "https": url}


def get_access_token():
    """네이버 커머스 API 액세스 토큰 발급"""
    env = _get_env()
    timestamp = str(int(time.time() * 1000))
    password = f"{env['client_id']}_{timestamp}"
    hashed = bcrypt.hashpw(password.encode(), env["client_secret"].encode())
    signature = base64.b64encode(hashed).decode()

    r = requests.post(
        f"{API_BASE}/v1/oauth2/token",
        data={
            "client_id": env["client_id"],
            "timestamp": timestamp,
            "client_secret_sign": signature,
            "grant_type": "client_credentials",
            "type": "SELF",
        },
        proxies=_get_proxies(),
    )
    if r.status_code != 200:
        raise RuntimeError(f"토큰 발급 실패: {r.text}")
    return r.json()["access_token"]


def get_changed_product_orders(token, last_changed_type="PAYED", hours_back=24):
    """최근 N시간 내 상태 변경된 주문 ID 조회"""
    now = datetime.now(KST)
    from_date = (now - timedelta(hours=hours_back)).isoformat(timespec="milliseconds")

    url = f"{API_BASE}/v1/pay-order/seller/product-orders/last-changed-statuses"
    r = requests.get(
        url,
        params={
            "lastChangedFrom": from_date,
            "lastChangedType": last_changed_type,
        },
        headers={"Authorization": f"Bearer {token}"},
        proxies=_get_proxies(),
    )
    if r.status_code != 200:
        raise RuntimeError(f"주문 상태 변경 조회 실패: {r.text}")
    return r.json().get("data", {}).get("lastChangeStatuses", [])


def get_order_details(token, product_order_ids):
    """상품주문 ID 리스트로 상세 정보 조회 (최대 300개씩)"""
    if not product_order_ids:
        return []

    url = f"{API_BASE}/v1/pay-order/seller/product-orders/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    all_orders = []
    for i in range(0, len(product_order_ids), 300):
        batch = product_order_ids[i : i + 300]
        r = requests.post(url, json={"productOrderIds": batch}, headers=headers, proxies=_get_proxies())
        if r.status_code != 200:
            raise RuntimeError(f"상세 조회 실패: {r.text}")
        data = r.json().get("data", [])
        all_orders.extend(data)
    return all_orders


def orders_by_status(status="PAYED", hours_back=24):
    """특정 상태의 주문 상세 정보 조회 (오래된 주문 먼저)"""
    token = get_access_token()
    changes = get_changed_product_orders(token, status, hours_back)
    product_order_ids = [c["productOrderId"] for c in changes]
    orders = get_order_details(token, product_order_ids)

    # 결제일 기준 오래된 주문 먼저 정렬
    orders.sort(
        key=lambda o: (
            o.get("productOrder", {}).get("paymentDate", ""),
            o.get("productOrder", {}).get("productOrderId", ""),
        )
    )
    return orders


def dispatch_orders(product_order_ids, token=None):
    """네이버 주문 발주확인 (PAYED → PLACE_ORDER)

    네이버 API: POST /pay-order/seller/product-orders/dispatch

    Args:
        product_order_ids: 상품주문ID 리스트
        token: 액세스 토큰 (없으면 자동 발급)

    Returns:
        dict: {"success": [ids], "failed": [{id, error}]}
    """
    if not product_order_ids:
        return {"success": [], "failed": []}

    if token is None:
        token = get_access_token()

    now = datetime.now(KST)
    dispatch_date = now.isoformat(timespec="milliseconds")

    url = f"{API_BASE}/v1/pay-order/seller/product-orders/dispatch"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 최대 300건씩 배치로 요청
    results = {"success": [], "failed": []}
    for i in range(0, len(product_order_ids), 300):
        batch = product_order_ids[i : i + 300]
        body = {
            "dispatchProductOrders": [
                {
                    "productOrderId": oid,
                    "dispatchDate": dispatch_date,
                    "deliveryMethodType": "DELIVERY",  # 택배
                }
                for oid in batch
            ]
        }
        r = requests.post(url, json=body, headers=headers, proxies=_get_proxies())
        if r.status_code != 200:
            for oid in batch:
                results["failed"].append({"id": oid, "error": r.text[:200]})
            continue

        data = r.json().get("data", {})
        succeeded = data.get("successProductOrderInfos", []) or []
        failed = data.get("failProductOrderInfos", []) or []
        for s in succeeded:
            results["success"].append(s.get("productOrderId"))
        for f in failed:
            results["failed"].append({
                "id": f.get("productOrderId"),
                "error": f.get("failMessage", "unknown"),
            })
    return results


def detect_special_orders(orders):
    """특이사항 있는 주문 감지 (결제대기/취소요청/반품요청 등)"""
    specials = []
    for wrap in orders:
        po = wrap.get("productOrder", {})
        status = po.get("productOrderStatus", "")
        # 정상 처리(PAYED)는 스킵
        if status == "PAYED":
            continue
        # 이미 처리된 것도 스킵
        if status in ("DELIVERING", "DELIVERED", "PURCHASE_DECIDED", "PLACE_ORDER"):
            continue

        reason_map = {
            "PAYMENT_WAITING": "결제대기/입금대기",
            "CANCELED": "취소됨",
            "CANCEL_REQUESTED": "취소요청",
            "RETURN_REQUESTED": "반품요청",
            "RETURNED": "반품됨",
            "EXCHANGE_REQUESTED": "교환요청",
            "EXCHANGED": "교환됨",
        }
        reason = reason_map.get(status, f"기타 ({status})")
        specials.append({
            "order_id": po.get("productOrderId"),
            "order_status": status,
            "reason": reason,
        })
    return specials


def orders_to_dada_rows(orders):
    """네이버 주문 → 더다 양식 DataFrame"""
    rows = []
    for wrap in orders:
        product_order = wrap.get("productOrder", {})
        order_info = wrap.get("order", {})

        # 취소된 건 제외
        status = product_order.get("productOrderStatus", "")
        if status in ("CANCELED", "RETURNED", "EXCHANGED"):
            continue

        rows.append({
            "고객주문번호": product_order.get("productOrderId", ""),
            "받는분성명": product_order.get("shippingAddress", {}).get("name", ""),
            "받는분전화번호": product_order.get("shippingAddress", {}).get("tel1", ""),
            "받는분기타연락처": product_order.get("shippingAddress", {}).get("tel2", ""),
            "받는분우편번호": product_order.get("shippingAddress", {}).get("zipCode", ""),
            "받는분주소(전체,분할)": _full_address(product_order.get("shippingAddress", {})),
            "상품명": _compose_product_name(product_order),
            "상품상세": "",
            "내품수량": product_order.get("quantity", 0),
            "배송메세지1": product_order.get("shippingMemo", "") or "",
            "송장번호": "",
            "출처": "스마트스토어",
        })
    return pd.DataFrame(rows)


def _full_address(addr):
    parts = [
        addr.get("baseAddress", ""),
        addr.get("detailedAddress", ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _compose_product_name(product_order):
    """스마트스토어 옵션정보를 기존 엑셀 다운로드 포맷과 동일하게 구성"""
    option_text = product_order.get("productOption", "")
    # 기존 엑셀 다운로드 시 옵션정보 컬럼 포맷을 그대로 사용
    return option_text if option_text else product_order.get("productName", "")


if __name__ == "__main__":
    print("네이버 스마트스토어 주문 조회 중...")
    orders = orders_by_status(status="PAYED", hours_back=24)
    print(f"조회된 주문: {len(orders)}건")

    df = orders_to_dada_rows(orders)
    print(f"더다 양식 행: {len(df)}")
    if len(df) > 0:
        print()
        for i, row in df.head(3).iterrows():
            print(f'--- 행{i+1} ---')
            for col, val in row.items():
                if val:
                    print(f'  {col}: {val}')
            print()
