import requests
import json

url = "http://127.0.0.1:5000/api/config/update"
payload = {
    "symbol": "ETHUSDT",
    "order_book_check_enabled": True,
    "support_resistance_check_enabled": True
}
headers = {"Content-Type": "application/json"}

try:
    print(f"Sending POST to {url} with {payload}")
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")
except Exception as e:
    print(f"Request failed: {e}")
