import pandas as pd
import numpy as np

def calculate_buy_stop_loss(file_path):
    # Read the CSV file containing timestamps and prices
    data = pd.read_csv(file_path)
    
    # Access the 'Price' column
    price_column = 'Price'
    
    # Calculate the standard deviation of the prices
    std_dev = np.std(data[price_column])
    
    # Current price (last price in the data)
    current_price = data[price_column].iloc[-1]
    
    # Calculate stop-loss limit (2 times standard deviation below the current price)
    stop_loss_limit = current_price - 2 * std_dev
    
    # Calculate buy limit (2 times standard deviation below the current price)
    buy_limit = current_price - 2 * std_dev
    
    # Calculate stop-loss percentage
    stop_loss_percentage = ((current_price - stop_loss_limit) / current_price) * 100
    
    # Calculate buy percentage
    buy_percentage = ((current_price - buy_limit) / current_price) * 100
    
    # Print the calculated buy and stop-loss percentages
    print(f"Stop-loss limit: {stop_loss_limit:.2f}")
    print(f"Stop-loss percentage: {stop_loss_percentage:.2f}%")
    print(f"Buy limit: {buy_limit:.2f}")
    print(f"Buy percentage: {buy_percentage:.2f}%")

# Call the function with the path to your CSV file
calculate_buy_stop_loss('solana_half_hourly_historical_data_2_days.csv')