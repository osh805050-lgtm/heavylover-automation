"""카페24 API 클라이언트 - 주문 조회 + 토큰 자동 갱신"""

import base64
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).parent / ".env"
API_VERSION = "2026-03-01"

# 토큰 갱신 시 동기화할 추가 .env 경로 (두 폴더가 각각 cafe24_client.py를 갖고 있으므로)
_EXTRA_ENV_PATHS = [
    Path("/root/heavylover-automation/.env"),
    Path("/root/heavylover-repurchase/.env"),
]


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    return {
        "mall_id": os.getenv("CAFE24_MALL_ID"),
        "client_id": os.getenv("CAFE24_CLIENT_ID"),
        "client_secret": os.getenv("CAFE24_CLIENT_SECRET"),
        "access_token": os.getenv("CAFE24_ACCESS_TOKEN"),
        "refresh_token": os.getenv("CAFE24_REFRESH_TOKEN"),
    }


def refresh_access_token():
    """Refresh Token으로 Access Token 재발급"""
    env = _get_env()
    auth_b64 = base64.b64encode(
        f"{env['client_id']}:{env['client_secret']}".encode()
    ).decode()

    url = f"https://{env['mall_id']}.cafe24api.com/api/v2/oauth/token"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": env["refresh_token"],
        },
    )
    if r.status_code != 200:
        raise RuntimeError(f"토큰 갱신 실패: {r.text}")

    result = r.json()
    access = result["access_token"]
    refresh = result["refresh_token"]

    # 현재 폴더 .env + 알려진 모든 경로에 동기화 (두 폴더 분리 구조 대응)
    targets = {ENV_PATH} | {p for p in _EXTRA_ENV_PATHS if p.exists()}
    for p in targets:
        set_key(str(p), "CAFE24_ACCESS_TOKEN", access)
        set_key(str(p), "CAFE24_REFRESH_TOKEN", refresh)

    return access


def _api_get(path, params=None):
    """토큰 만료 시 자동 갱신하며 GET 호출"""
    env = _get_env()
    url = f"https://{env['mall_id']}.cafe24api.com{path}"
    headers = {
        "Authorization": f"Bearer {env['access_token']}",
        "X-Cafe24-Api-Version": API_VERSION,
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 401:
        new_token = refresh_access_token()
        headers["Authorization"] = f"Bearer {new_token}"
        r = requests.get(url, headers=headers, params=params)
    return r


def _api_put(path, body):
    """토큰 만료 시 자동 갱신하며 PUT 호출"""
    env = _get_env()
    url = f"https://{env['mall_id']}.cafe24api.com{path}"
    headers = {
        "Authorization": f"Bearer {env['access_token']}",
        "X-Cafe24-Api-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    r = requests.put(url, headers=headers, json=body)
    if r.status_code == 401:
        new_token = refresh_access_token()
        headers["Authorization"] = f"Bearer {new_token}"
        r = requests.put(url, headers=headers, json=body)
    return r


def _api_post(path, body):
    """토큰 만료 시 자동 갱신하며 POST 호출"""
    env = _get_env()
    url = f"https://{env['mall_id']}.cafe24api.com{path}"
    headers = {
        "Authorization": f"Bearer {env['access_token']}",
        "X-Cafe24-Api-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json=body)
    if r.status_code == 401:
        new_token = refresh_access_token()
        headers["Authorization"] = f"Bearer {new_token}"
        r = requests.post(url, headers=headers, json=body)
    return r


def change_item_to_shipping_ready(order_id, item_no, status="N20"):
    """주문 아이템을 상품준비중(N1) → 배송준비중(N20)으로 변경

    Cafe24 API: PUT /api/v2/admin/orders/{order_id}/items/{item_no}

    Args:
        order_id: 주문 ID (예: "20260420-0000014")
        item_no: 아이템 번호 (주문 내 순번, 예: 1, 2, 3)
        status: 변경할 상태 코드 ("N20" = 배송준비중)
    """
    body = {
        "shop_no": 1,
        "request": {
            "status": status,
        },
    }
    return _api_put(f"/api/v2/admin/orders/{order_id}/items/{item_no}", body)


def move_shipping_ready(days_back=7):
    """상품준비중(N1) 아이템 전부 배송준비중(N2)으로 일괄 변경"""
    orders = fetch_orders(days_back=days_back)
    targets = []
    for order in orders:
        if order.get("canceled") == "T":
            continue
        for item in (order.get("items") or []):
            if item.get("status_code") == "N1":
                targets.append((order.get("order_id"), item.get("order_item_code")))

    results = {"success": [], "failed": []}
    for order_id, item_code in targets:
        try:
            r = change_item_to_shipping_ready(order_id, item_code)
            if r.status_code in (200, 201):
                results["success"].append({"order_id": order_id, "item_code": item_code})
            else:
                results["failed"].append({
                    "order_id": order_id,
                    "item_code": item_code,
                    "status": r.status_code,
                    "error": r.text[:200],
                })
        except Exception as e:
            results["failed"].append({
                "order_id": order_id,
                "item_code": item_code,
                "error": str(e),
            })
    return results


def fetch_orders(days_back=1):
    """최근 N일 주문 조회 (오래된 주문 → 최신 주문 순으로 정렬)"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)

    all_orders = []
    offset = 0
    limit = 100

    while True:
        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "embed": "items,receivers",
            "limit": limit,
            "offset": offset,
        }
        r = _api_get("/api/v2/admin/orders", params=params)
        if r.status_code != 200:
            raise RuntimeError(f"주문 조회 실패: {r.status_code} {r.text}")

        orders = r.json().get("orders", [])
        all_orders.extend(orders)
        if len(orders) < limit:
            break
        offset += limit

    # 카페24 관리자 엑셀과 동일하게 오래된 주문 먼저
    all_orders.sort(key=lambda o: (o.get("order_date", ""), o.get("order_id", "")))
    return all_orders


def orders_to_dada_rows(orders):
    """카페24 주문 리스트 → 더다 양식 DataFrame

    order_status 기준 필터:
    - N20 = 배송준비중 → **포함** (엑셀 대상)
    - N10 = 상품준비중 → 제외 (수동 배송준비중 전환 필요 → 알림)
    - N30 = 배송중 → 제외 (이미 출고됨)
    - N40 = 배송완료 → 제외
    - N00 = 입금전, C** = 취소/반품/교환 → 제외 (특이사항으로 별도 처리)
    """
    rows = []
    for order in orders:
        # 취소된 주문은 제외
        if order.get("canceled") == "T":
            continue

        receivers = order.get("receivers", []) or []
        if not receivers:
            continue
        receiver = receivers[0]

        items = order.get("items", []) or []
        for item in items:
            order_status = item.get("order_status", "")
            # 배송준비중(N20)만 포함
            if order_status != "N20":
                continue

            rows.append({
                "고객주문번호": order.get("order_id", ""),
                "받는분성명": receiver.get("name", ""),
                "받는분전화번호": receiver.get("cellphone", ""),
                "받는분기타연락처": "",
                "받는분우편번호": receiver.get("zipcode", ""),
                "받는분주소(전체,분할)": receiver.get("address_full", ""),
                "상품명": item.get("option_value", ""),
                "상품상세": "",
                "내품수량": item.get("quantity", 0),
                "배송메세지1": receiver.get("shipping_message", ""),
                "송장번호": "",
                "출처": "카페24",
            })

    return pd.DataFrame(rows)


def detect_special_orders(orders):
    """특이사항 주문 감지

    - N10 (상품준비중): 수동 배송준비중 전환 필요 → 사용자에게 알림
    - N00 (입금전), C** (취소/반품/교환): 확인 필요
    - 기타 비정상: 확인 필요
    """
    specials = []
    for order in orders:
        if order.get("canceled") == "T":
            specials.append({
                "order_id": order.get("order_id"),
                "item_code": None,
                "order_status": "CANCELED",
                "status_text": "주문 전체 취소",
                "reason": "취소된 주문",
            })
            continue

        for item in (order.get("items") or []):
            order_status = item.get("order_status", "")
            status_text = item.get("status_text", "")

            # 배송준비중(N20)은 정상 처리 대상이라 스킵
            if order_status == "N20":
                continue
            # 이미 출고된 것도 스킵(배송중/배송완료)
            if order_status in ("N30", "N40"):
                continue

            # 상품준비중 → 배송준비중 전환 필요
            if order_status == "N10":
                reason = "상품준비중 → 배송준비중 수동 전환 필요"
            elif order_status == "N00":
                reason = "입금전"
            elif order_status and order_status.startswith("C"):
                reason = f"취소/반품/교환 ({status_text})"
            else:
                reason = f"기타 ({status_text or order_status})"

            specials.append({
                "order_id": order.get("order_id"),
                "item_code": item.get("order_item_code"),
                "order_status": order_status,
                "status_text": status_text,
                "reason": reason,
            })

    return specials


if __name__ == "__main__":
    print("카페24 API로 주문 조회 중...")
    orders = fetch_orders(days_back=3)
    print(f"조회된 주문: {len(orders)}건")

    df = orders_to_dada_rows(orders)
    print(f"더다 양식 행 수: {len(df)}")
    print()
    print(df.head(10).to_string())
