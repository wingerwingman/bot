import requests
import time
import sys

url = "http://127.0.0.1:5050/api/status?type=spot&symbol=live_ETHUSDT"
last_price = "INIT"

print(f"Monitoring {url} for 40 seconds...")

for i in range(20):
    try:
        r = requests.get(url, timeout=2)
        if r.status_code != 200:
             print(f"Time {i}: HTTP {r.status_code}")
             continue
             
        data = r.json()
        bal = data.get('balances')
        
        if not bal:
             print(f"Time {i}: Balances MISSING in response!")
             continue
             
        bp = bal.get('bought_price')
        
        # Log status
        run_status = data.get('running')
        
        print(f"Time {i}: Running={run_status}, BoughtPrice={bp}")
        
    except Exception as e:
        print(f"Time {i}: Error {e}")
        
    time.sleep(2)
