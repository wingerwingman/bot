import pandas as pd
import numpy as np

# Load Ethereum historical data from CSV
ethereum_data = pd.read_csv("solana_half_hourly_historical_data_2_days.csv")

# Convert the 'Date' column to datetime format if needed
ethereum_data['Date'] = pd.to_datetime(ethereum_data['Date'])

# Calculate Daily Returns
ethereum_data["Daily_Returns"] = ethereum_data["Price"].pct_change()

# Determine Volatility (Standard Deviation of Daily Returns)
volatility = ethereum_data["Daily_Returns"].std()

# Set Stop Loss (e.g., 2 times volatility)
stop_loss_percent = 2 * volatility

# Set Sell Percent (e.g., 3 times volatility)
sell_percent = 3 * volatility

print("Volatility:", volatility)
print("Stop Loss Percent:", stop_loss_percent)
print("Sell Percent:", sell_percent)