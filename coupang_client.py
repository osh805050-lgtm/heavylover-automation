"""쿠팡 Wing Open API 클라이언트 - 주문 조회 + 더다 양식 변환"""

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
KST = timezone(timedelta(hours=9))
API_BASE = "https://api-gateway.coupang.com"


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    return {
        "vendor_id": os.getenv("COUPANG_VENDOR_ID"),
        "access_key": os.getenv("COUPANG_ACCESS_KEY"),
        "secret_key": os.getenv("COUPANG_SECRET_KEY"),
    }


def _make_signature(method, path, query, secret_key):
    """쿠팡 HMAC-SHA256 서명 생성"""
    datetime_str = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = datetime_str + method + path + query
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return datetime_str, signature


def _auth_header(method, path, query, env):
    """Authorization 헤더 생성"""
    datetime_str, signature = _make_signature(method, path, query, env["secret_key"])
    return {
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={env['access_key']}, "
            f"signed-date={datetime_str}, signature={signature}"
        ),
        "X-Requested-By": env["vendor_id"],
        "Content-Type": "application/json;charset=UTF-8",
    }


def fetch_orders(days_back=1):
    """발주서 목록 조회 (분단위 전체, INSTRUCT 상태 = 상품준비중/배송준비)

    days_back: 며칠 전까지 조회할지 (기본 1일)
    반환: 발주서 raw dict 리스트
    """
    env = _get_env()
    if not env["vendor_id"] or not env["access_key"] or not env["secret_key"]:
        raise RuntimeError("쿠팡 API 키 미설정 — .env에 COUPANG_VENDOR_ID/ACCESS_KEY/SECRET_KEY 추가 필요")

    now = datetime.now(KST)
    created_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M")
    created_to = now.strftime("%Y-%m-%dT%H:%M")

    path = f"/v2/providers/openapi/apis/api/v4/vendors/{env['vendor_id']}/ordersheets"
    query = (
        f"createdAtFrom={created_from}"
        f"&createdAtTo={created_to}"
        f"&searchType=timeFrame"
        f"&status=INSTRUCT"
        f"&maxPerPage=50"
    )

    all_orders = []
    page = 1

    while True:
        paged_query = query + f"&pageIndex={page}"
        headers = _auth_header("GET", path, paged_query, env)
        # params= 사용 금지 — requests가 URL을 재조합하면 서명 query와 불일치 발생
        r = requests.get(
            f"{API_BASE}{path}?{paged_query}",
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"쿠팡 주문 조회 실패 ({r.status_code}): {r.text[:300]}")

        body = r.json()
        data = body.get("data", []) or []
        all_orders.extend(data)

        # 다음 페이지 없으면 종료
        if len(data) < 50:
            break
        page += 1
        time.sleep(0.5)

    return all_orders


def detect_special_orders(orders):
    """특이사항 주문 감지 (취소요청·반품요청 등)"""
    specials = []
    for order in orders:
        status = order.get("status", "")
        order_id = order.get("orderId", "")
        if status in ("CANCEL_REQUEST", "RETURN_REQUEST", "EXCHANGE_REQUEST"):
            specials.append({
                "order_id": order_id,
                "reason": f"상태이상({status})",
            })
    return specials


def orders_to_dada_rows(orders):
    """쿠팡 발주서 리스트 → 더다 양식 DataFrame"""
    rows = []
    for order in orders:
        receiver = order.get("receiver", {})
        order_items = order.get("orderItems", [])

        # 상품명: 여러 품목이면 첫 번째 + 외 N건
        if not order_items:
            continue
        item_names = [it.get("vendorItemName", "") for it in order_items]
        product_name = item_names[0]
        if len(item_names) > 1:
            product_name += f" 외 {len(item_names) - 1}건"

        # 상품상세: 전 품목 수량 합산 표시
        detail_parts = [
            f"{it.get('vendorItemName', '')} x{it.get('shippingCount', 1)}"
            for it in order_items
        ]
        product_detail = " / ".join(detail_parts)

        # 총 수량
        total_qty = sum(it.get("shippingCount", 1) for it in order_items)

        # 주소 조합
        addr = f"{receiver.get('addr1', '')} {receiver.get('addr2', '')}".strip()

        rows.append({
            "고객주문번호": str(order.get("orderId", "")),
            "받는분성명": receiver.get("name", ""),
            "받는분전화번호": receiver.get("safeNumber", ""),  # 쿠팡 안심번호
            "받는분기타연락처": "",
            "받는분우편번호": receiver.get("postCode", ""),
            "받는분주소(전체,분할)": addr,
            "상품명": product_name,
            "상품상세": product_detail,
            "내품수량": total_qty,
            "배송메세지1": order.get("deliveryMemo", ""),
            "송장번호": "",
        })

    return pd.DataFrame(rows)
