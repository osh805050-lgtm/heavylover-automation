"""
카페24 OAuth 토큰 교환 스크립트
- 인증 코드 → Access Token + Refresh Token
- .env에 저장
"""

import base64
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)


def exchange_code_for_token():
    mall_id = os.getenv("CAFE24_MALL_ID")
    client_id = os.getenv("CAFE24_CLIENT_ID")
    client_secret = os.getenv("CAFE24_CLIENT_SECRET")
    redirect_uri = os.getenv("CAFE24_REDIRECT_URI")
    code = os.getenv("CAFE24_AUTH_CODE")

    # Basic 인증 헤더 생성
    auth_str = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()

    url = f"https://{mall_id}.cafe24api.com/api/v2/oauth/token"
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    response = requests.post(url, headers=headers, data=data)

    if response.status_code != 200:
        print(f"실패: {response.status_code}")
        print(response.text)
        sys.exit(1)

    result = response.json()
    access_token = result["access_token"]
    refresh_token = result["refresh_token"]

    # .env 파일에 저장
    set_key(str(ENV_PATH), "CAFE24_ACCESS_TOKEN", access_token)
    set_key(str(ENV_PATH), "CAFE24_REFRESH_TOKEN", refresh_token)

    print("토큰 발급 성공!")
    print(f"Access Token 만료: {result.get('expires_at')}")
    print(f"Refresh Token 만료: {result.get('refresh_token_expires_at')}")
    print(f"권한: {result.get('scopes')}")

    return access_token


def test_orders_api(access_token=None):
    """주문 조회 API 테스트"""
    if access_token is None:
        access_token = os.getenv("CAFE24_ACCESS_TOKEN")

    mall_id = os.getenv("CAFE24_MALL_ID")

    # 최근 7일 주문 조회
    from datetime import datetime, timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    url = f"https://{mall_id}.cafe24api.com/api/v2/admin/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Cafe24-Api-Version": "2024-09-01",
    }
    params = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "limit": 5,
    }

    response = requests.get(url, headers=headers, params=params)

    print(f"\n=== 주문 조회 API 테스트 ===")
    print(f"상태코드: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        orders = data.get("orders", [])
        print(f"최근 7일 주문 수: {len(orders)}건 (최대 5건 표시)")
        for idx, order in enumerate(orders[:3], 1):
            print(f"\n--- 주문 {idx} ---")
            print(f"  주문번호: {order.get('order_id')}")
            print(f"  주문일: {order.get('order_date')}")
            print(f"  주문자: {order.get('buyer_name')}")
            print(f"  결제금액: {order.get('payment_amount')}")
        return True
    else:
        print(f"에러: {response.text}")
        return False


if __name__ == "__main__":
    print("=== 카페24 토큰 발급 ===")
    access_token = exchange_code_for_token()
    test_orders_api(access_token)
