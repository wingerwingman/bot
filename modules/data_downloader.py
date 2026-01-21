import requests
import csv
import datetime
import os
import time

def download_historical_data(symbol, interval="15m", days=90, output_dir="data"):
    """
    Downloads historical kline data from Binance US and saves to CSV.
    Returns the absolute path of the saved file.
    """
    url = "https://api.binance.us/api/v3/klines"
    
    # Calculate timestamps
    now = datetime.datetime.now()
    start_date = now - datetime.timedelta(days=int(days))
    
    start_ts = int(start_date.timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)
    
    all_data = []
    limit = 1000
    current_start = start_ts
    
    print(f"Downloading {symbol} data from {start_date} to {now}...")
    
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
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                raise Exception(f"Binance API Error: {response.text}")
                
            data = response.json()
            
            if not isinstance(data, list):
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
            
            last_timestamp = data[-1][0]
            current_start = last_timestamp + 1
            
            if last_timestamp >= end_ts or len(data) < limit:
                break
                
            time.sleep(0.1) # Rate limit nicest
            
        except Exception as e:
            print(f"Download Exception: {e}")
            raise e
            
    if not all_data:
        raise Exception("No data fetched from Binance.")

    # Save to CSV
    filename = f"{symbol.lower()}_{interval}_data.csv"
    # Ensure output path is absolute or relative to project root (assuming caller handles CWD or passes abs path)
    # If output_dir is relative, make it absolute based on CWD
    if not os.path.isabs(output_dir):
        output_dir = os.path.abspath(output_dir)
        
    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, filename)
    
    with open(full_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        writer.writerows(all_data)
        
    return filename
