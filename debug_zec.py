
from binance import Client
import os
import sys

# Mock config
API_KEY = "mock_key"
API_SECRET = "mock_secret"
# Try to load real config
try:
    sys.path.append(os.getcwd())
    from modules import config
    API_KEY = config.API_KEY
    API_SECRET = config.API_SECRET
except ImportError:
    pass

try:
    print("Initializing Client for ZECUSD...")
    client = Client(API_KEY, API_SECRET, tld='us')
    
    symbol = "ZECUSD"
    print(f"Fetching 1m klines for {symbol}...")
    klines = client.get_klines(symbol=symbol, interval='1m', limit=5)
    
    if klines:
        last_close = float(klines[-1][4])
        print(f"ZECUSD 1m close: {last_close}")
    else:
        print("No ZECUSD 1m data.")
        
    print(f"Fetching 4h klines for {symbol}...")
    klines_4h = client.get_historical_klines(symbol, Client.KLINE_INTERVAL_4HOUR, "1 day ago UTC")
    if klines_4h:
        last_close_4h = float(klines_4h[-1][4])
        print(f"ZECUSD 4h close: {last_close_4h}")
        
    # Check ZECUSDT as well
    symbol_t = "ZECUSDT"
    print(f"Fetching 1m klines for {symbol_t}...")
    try:
        klines_t = client.get_klines(symbol=symbol_t, interval='1m', limit=5)
        last_close_t = float(klines_t[-1][4])
        print(f"ZECUSDT 1m close: {last_close_t}")
    except Exception as e:
        print(f"ZECUSDT failed: {e}")

except Exception as e:
    print(f"Error: {e}")
