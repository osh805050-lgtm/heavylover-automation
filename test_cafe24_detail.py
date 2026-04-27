"""카페24 주문 items + receivers 구조 확인"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

mall_id = os.getenv("CAFE24_MALL_ID")
access_token = os.getenv("CAFE24_ACCESS_TOKEN")

url = f"https://{mall_id}.cafe24api.com/api/v2/admin/orders"
headers = {
    "Authorization": f"Bearer {access_token}",
    "X-Cafe24-Api-Version": "2024-09-01",
}
end_date = datetime.now()
start_date = end_date - timedelta(days=3)
params = {
    "start_date": start_date.strftime("%Y-%m-%d"),
    "end_date": end_date.strftime("%Y-%m-%d"),
    "embed": "buyer,items,receivers",
    "limit": 1,
}

response = requests.get(url, headers=headers, params=params)
import json
order = response.json()["orders"][0]

print("=== buyer ===")
print(json.dumps(order.get("buyer", {}), ensure_ascii=False, indent=2, default=str))
print("\n=== receivers ===")
print(json.dumps(order.get("receivers", []), ensure_ascii=False, indent=2, default=str))
print("\n=== items (1개만) ===")
items = order.get("items", [])
if items:
    print(json.dumps(items[0], ensure_ascii=False, indent=2, default=str))
