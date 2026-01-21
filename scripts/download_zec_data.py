import requests
import csv
import datetime
import os
import time

# --- CONFIGURATION ---
SYMBOL = "ZECUSDT"
INTERVAL = "15m"  # 15 minute interval
DAYS = 90         # Download last 90 days

# Resolve absolute path to data directory
current_dir = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(current_dir, "..", "data", "zec_data.csv")

def get_binance_data(symbol, interval, start_str, end_str=None):
    url = "https://api.binance.us/api/v3/klines"
    
    # Convert dates to milliseconds
    start_ts = int(start_str.timestamp() * 1000)
    end_ts = int(end_str.timestamp() * 1000) if end_str else None
    
    all_data = []
    limit = 1000
    
    current_start = start_ts
    
    print(f"Downloading {symbol} data from {start_str} to {end_str}...")
    
    while True:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": limit
        }
        if end_ts:
            params["endTime"] = end_ts
            
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            if not isinstance(data, list):
                print(f"Error: {data}")
                break
                
            if len(data) == 0:
                break
                
            for candle in data:
                # Binance response: [Open Time, Open, High, Low, Close, Volume, ...]
                timestamp = datetime.datetime.fromtimestamp(candle[0] / 1000)
                open_price = float(candle[1])
                high_price = float(candle[2])
                low_price = float(candle[3])
                close_price = float(candle[4])
                volume = float(candle[5])
                
                all_data.append([timestamp, open_price, high_price, low_price, close_price, volume])
            
            # Update start time for next batch
            last_timestamp = data[-1][0]
            current_start = last_timestamp + 1
            
            # Check if we reached end (or current time)
            if end_ts and last_timestamp >= end_ts:
                break
            if len(data) < limit:
                break
                
            # Respect rate limits
            time.sleep(0.1)
            print(f"Fetched {len(all_data)} candles...", end='\r')
            
        except Exception as e:
            print(f"Exception: {e}")
            break
            
    return all_data

def save_to_csv(data, filename):
    # Ensure directory exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        writer.writerows(data)
    print(f"\nSaved {len(data)} records to {filename}")

if __name__ == "__main__":
    now = datetime.datetime.now()
    start_date = now - datetime.timedelta(days=DAYS)
    
    data = get_binance_data(SYMBOL, INTERVAL, start_date, now)
    save_to_csv(data, OUTPUT_FILE)
