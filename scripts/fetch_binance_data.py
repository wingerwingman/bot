#!/usr/bin/env python3
"""
Fetch historical kline data using Binance API
More reliable than CoinGecko, higher rate limits

Usage:
    python scripts/fetch_binance_data.py
    python scripts/fetch_binance_data.py --symbol BTCUSDT --interval 1h --days 30
"""
import pandas as pd
import os
import argparse
from datetime import datetime, timedelta

try:
    from binance import Client
except ImportError:
    print("Error: binance-connector not installed. Run: pip install binance-connector")
    exit(1)

# Load environment if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

def fetch_binance_klines(symbol='ETHUSDT', interval='30m', days=2, api_key=None, api_secret=None):
    """
    Fetch historical kline (candlestick) data from Binance.
    
    Parameters:
        - symbol: Trading pair (e.g., ETHUSDT, BTCUSDT)
        - interval: Candlestick interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
        - days: Number of days of data to fetch
        
    Returns:
        - DataFrame with OHLCV data
    """
    # Use env vars or passed keys
    key = api_key or os.getenv('BINANCE_US_API_KEY', '')
    secret = api_secret or os.getenv('BINANCE_US_API_SECRET', '')
    
    # Binance US uses tld='us'
    client = Client(key, secret, tld='us')
    
    # Calculate timestamps
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)
    
    print(f"Fetching {days} days of {symbol} ({interval}) from Binance US...")
    
    klines = client.get_historical_klines(
        symbol=symbol,
        interval=interval,
        start_str=start_ts,
        end_str=end_ts
    )
    
    if not klines:
        print("No data returned from Binance")
        return None
    
    # Convert to DataFrame
    columns = [
        'Open Time', 'Open', 'High', 'Low', 'Close', 'Volume',
        'Close Time', 'Quote Asset Volume', 'Number of Trades',
        'Taker Buy Base Volume', 'Taker Buy Quote Volume', 'Ignore'
    ]
    
    df = pd.DataFrame(klines, columns=columns)
    
    # Convert timestamps and prices
    df['Timestamp'] = pd.to_datetime(df['Open Time'], unit='ms')
    df['Price'] = df['Close'].astype(float)  # Use close price
    df['Open'] = df['Open'].astype(float)
    df['High'] = df['High'].astype(float)
    df['Low'] = df['Low'].astype(float)
    df['Volume'] = df['Volume'].astype(float)
    
    # Keep useful columns
    df = df[['Timestamp', 'Open', 'High', 'Low', 'Price', 'Volume']]
    
    print(f"Retrieved {len(df)} candlesticks")
    return df

def main():
    parser = argparse.ArgumentParser(description='Fetch historical data from Binance')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='Trading pair (default: ETHUSDT)')
    parser.add_argument('--interval', type=str, default='30m', 
                       help='Interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d (default: 30m)')
    parser.add_argument('--days', type=int, default=7, help='Days of data (default: 7)')
    parser.add_argument('--output', type=str, default=None, help='Output filename')
    args = parser.parse_args()
    
    df = fetch_binance_klines(
        symbol=args.symbol,
        interval=args.interval,
        days=args.days
    )
    
    if df is not None:
        os.makedirs('data', exist_ok=True)
        
        if args.output:
            filename = args.output
        else:
            filename = f"data/{args.symbol.lower()}_{args.interval}_{args.days}d.csv"
        
        df.to_csv(filename, index=False)
        print(f"Saved to: {filename}")
        print(f"\nSample data:")
        print(df.head())

if __name__ == "__main__":
    main()
