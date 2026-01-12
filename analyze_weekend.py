import os
import sys
from binance.client import Client
from datetime import datetime
import pandas as pd

# Mock Config if needed, or just use public client
api_key = os.environ.get('BINANCE_US_API_KEY')
api_secret = os.environ.get('BINANCE_US_API_SECRET')

def analyze():
    print("Connecting to Binance...")
    try:
        client = Client(tld='us') # Public data doesn't strictly need keys usually, but tld='us' might
    except Exception as e:
        print(f"Client Init Error: {e}")
        return

    symbol = 'ETHUSDT'
    # Start: Jan 10 08:49
    # End: Jan 12 08:28
    # Let's grab 1h Intervals
    print(f"Fetching {symbol} data for analysis...")
    
    # Simple timestamp conversion 
    # 2026-01-10 08:49 to now
    start_str = "2026-01-10 08:00:00" 
    
    try:
        klines = client.get_historical_klines(symbol, Client.KLINE_INTERVAL_15MINUTE, start_str)
    except Exception as e:
        print(f"Fetch Error: {e}")
        return

    if not klines:
        print("No data found.")
        return

    # entry = 3096.72
    entry_price = 3096.72
    fee_pct = 0.001
    break_even = entry_price * (1 + 2 * fee_pct)
    
    print(f"\n--- Strategy Simulation ---")
    print(f"Entry: {entry_price:.2f}")
    print(f"BreakEven: {break_even:.2f}")
    
    peak = entry_price
    
    # Params
    # OLD: Vol~2.7% -> Trail 8.2% (approx)
    old_trail_pct = 0.082
    # NEW: Trail 4.1%
    new_trail_pct = 0.041
    
    sold_old = False
    sold_new = False
    
    max_price = 0
    
    print(f"\nTime | High | PnL% | Peak | Old Trig | New Trig")
    
    for k in klines:
        ts = datetime.fromtimestamp(k[0]/1000)
        high = float(k[2])
        low = float(k[3])
        close = float(k[4])
        
        if high > peak:
            peak = high
            
        max_price = max(max_price, high)
        
        # Check Trails
        # Only active if Peak > BreakEven
        
        # OLD STRATEGY
        if not sold_old:
            old_trigger = peak * (1 - old_trail_pct)
            if peak > break_even and low < old_trigger:
                print(f"★ OLD STRATEGY SOLD @ {old_trigger:.2f} on {ts} (Peak {peak:.2f})")
                sold_old = True
                
        # NEW STRATEGY
        if not sold_new:
            new_trigger = peak * (1 - new_trail_pct)
            if peak > break_even and low < new_trigger:
                 print(f"☆ NEW STRATEGY SOLD @ {new_trigger:.2f} on {ts} (Peak {peak:.2f})")
                 sold_new = True

    print(f"\n--- Summary ---")
    print(f"Max Price Reached: {max_price:.2f} (+{((max_price-entry_price)/entry_price)*100:.2f}%)")
    if not sold_old: print("Old Strategy (8%): HELD (Never hit trigger)")
    if not sold_new: print("New Strategy (4%): HELD (Never hit trigger)")
    
if __name__ == "__main__":
    analyze()
