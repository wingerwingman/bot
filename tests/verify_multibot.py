import requests
import time

BASE_URL = "http://localhost:5000"
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'test_token_123') 

import sys
import os
sys.path.append(os.getcwd())

from modules.server import app, check_auth

def test_multibot():
    # Mock Auth
    app.config['TESTING'] = True
    
    # Check config for token
    from modules import config
    token = config.ADMIN_TOKEN or 'test_token_123'
    headers = {'X-Auth-Token': token}

    with app.test_client() as client:
        print("1. Starting Spot Bot (ETHUSDT)...")
        res = client.post('/api/start', json={
            "base_asset": "ETH",
            "quote_asset": "USDT",
            "mode": "test",
            "filename": "ETHUSDT_1h_30d.csv" # Need a valid file mock or real
        }, headers=headers)
        
        # If file missing, might fail. Let's assume we need to mock or ensure file exists.
        # Actually, let's just use 'live' mode but mock the Binance client to avoid trade placement? 
        # Or just create a dummy CSV.
        
        # Create dummy CSV
        os.makedirs('data', exist_ok=True)
        with open('data/test_data.csv', 'w') as f:
            f.write("Timestamp,Open,High,Low,Close,Volume\n")
            f.write("2023-01-01 00:00:00,100,110,90,105,1000\n")
            
        res = client.post('/api/start', json={
            "base_asset": "ETH",
            "quote_asset": "USDT",
            "mode": "test",
            "filename": "test_data.csv"
        }, headers=headers)
        print(f"Start Spot: {res.status_code} {res.json}")
        
        print("\n2. Starting Grid Bot (BTCUSDT)...")
        res = client.post('/api/grid/start', json={
            "symbol": "BTCUSDT",
            "is_live": False,
            "capital": 1000
        }, headers=headers)
        print(f"Start Grid: {res.status_code} {res.json}")
        
        print("\n3. Checking Status (Should see both)...")
        res = client.get('/api/status', headers=headers)
        data = res.json
        # Check for 'bots' list
        if 'bots' in data:
            print(f"Active Bots: {len(data['bots'])}")
            for b in data['bots']:
                print(f" - {b['type']} {b['symbol']} ({b['status']})")
        else:
             print("ERROR: 'bots' list not found in status response")
             print(data)
             
        print("\n4. Stopping Spot Bot only...")
        res = client.post('/api/stop', json={"symbol": "ETHUSDT"}, headers=headers)
        print(f"Stop response: {res.json}")
        
        print("\n5. Checking Status (BTC Grid should still be running)...")
        res = client.get('/api/status', headers=headers)
        data = res.json
        bots = data.get('bots', [])
        print(f"Active Bots: {len(bots)}")
        for b in bots:
            print(f" - {b['type']} {b['symbol']} ({b['status']})")

if __name__ == "__main__":
    try:
        test_multibot()
        print("\n✅ API Verification Complete")
    except Exception as e:
        print(f"\n❌ Verification Failed: {e}")
