#!/usr/bin/env python3
"""
Fetch ETH historical data using CoinGecko API
Saves to data/ folder for backtesting

Usage:
    python scripts/fetch_eth_coingecko.py
    python scripts/fetch_eth_coingecko.py --days 7
"""
import pandas as pd
import requests
import time
import os
import argparse

def get_ethereum_data(days=2, interval_minutes=30):
    """
    Get Ethereum (ETH) price data from CoinGecko API.
    
    Parameters:
        - days: Number of days of historical data
        - interval_minutes: Data granularity (30 = half-hourly)
    
    Returns:
        - DataFrame with Timestamp and Price columns
    """
    end_timestamp = int(time.time())
    start_timestamp = end_timestamp - (days * 24 * 60 * 60)
    
    interval_seconds = interval_minutes * 60
    all_data = []
    
    current_timestamp = start_timestamp
    request_count = 0
    
    print(f"Fetching {days} days of ETH data from CoinGecko...")
    
    while current_timestamp < end_timestamp:
        next_timestamp = min(current_timestamp + interval_seconds * 100, end_timestamp)  # Batch requests
        url = f"https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range?vs_currency=usd&from={current_timestamp}&to={next_timestamp}"
        
        try:
            response = requests.get(url)
            request_count += 1
            
            if response.status_code == 429:  # Rate limit
                print("Rate limit hit. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            response.raise_for_status()
            data = response.json()
            
            if 'prices' in data:
                for price_data in data['prices']:
                    timestamp_ms = price_data[0]
                    price = price_data[1]
                    date = pd.to_datetime(timestamp_ms, unit='ms')
                    all_data.append({'Timestamp': date, 'Price': price})
            
            current_timestamp = next_timestamp
            
            # Progress indicator
            if request_count % 10 == 0:
                print(f"  Fetched {len(all_data)} data points...")
                
            # Rate limit protection
            time.sleep(1.5)
            
        except Exception as e:
            print(f"Error: {e}")
            break
    
    if all_data:
        df = pd.DataFrame(all_data)
        df = df.drop_duplicates(subset=['Timestamp']).sort_values('Timestamp')
        print(f"Total: {len(df)} data points")
        return df
    else:
        print("No data retrieved.")
        return None

def main():
    parser = argparse.ArgumentParser(description='Fetch ETH data from CoinGecko')
    parser.add_argument('--days', type=int, default=2, help='Number of days (default: 2)')
    parser.add_argument('--output', type=str, default=None, help='Output filename')
    args = parser.parse_args()
    
    df = get_ethereum_data(days=args.days)
    
    if df is not None:
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        
        # Generate filename
        if args.output:
            filename = args.output
        else:
            filename = f"data/eth_coingecko_{args.days}d.csv"
        
        df.to_csv(filename, index=False)
        print(f"Saved to: {filename}")

if __name__ == "__main__":
    main()
