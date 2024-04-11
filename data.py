import pandas as pd
import numpy as np

def generate_ethereum_data(start_date, end_date, frequency='D', initial_price=2000, volatility=0.05):
    """
    Generate synthetic Ethereum price data.

    Parameters:
        - start_date: Start date of the data (string in 'YYYY-MM-DD' format)
        - end_date: End date of the data (string in 'YYYY-MM-DD' format)
        - frequency: Frequency of data (default is 'D' for daily)
        - initial_price: Initial price of Ethereum
        - volatility: Volatility of the price data

    Returns:
        - DataFrame containing synthetic Ethereum price data
    """
    dates = pd.date_range(start=start_date, end=end_date, freq=frequency)
    prices = [initial_price]

    for _ in range(1, len(dates)):
        price_change = np.random.normal(0, volatility)
        new_price = prices[-1] * (1 + price_change)
        prices.append(new_price)

    df = pd.DataFrame({'Date': dates, 'Price': prices})
    return df

def save_to_csv(df, filename):
    """
    Save DataFrame to a CSV file.

    Parameters:
        - df: DataFrame to be saved
        - filename: Name of the CSV file
    """
    df.to_csv(filename, index=False)

# Generate synthetic Ethereum price data for January 2022
start_date = '2023-01-01'
end_date = '2024-03-31'
ethereum_data = generate_ethereum_data(start_date, end_date)

# Save the data to a CSV file
filename = 'ethereum_historical_data.csv'
save_to_csv(ethereum_data, filename)