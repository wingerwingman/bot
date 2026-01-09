import pandas as pd
import requests
import time

def get_ethereum_half_hourly_data(start_date, end_date):
    """
    Get Ethereum (ETH) half-hourly price data from the CoinGecko API.

    Parameters:
        - start_date: Start date of the data (string in 'YYYY-MM-DD' format)
        - end_date: End date of the data (string in 'YYYY-MM-DD' format)

    Returns:
        - DataFrame containing Ethereum (ETH) half-hourly price data
    """
    # Convert start_date and end_date to Unix timestamps in seconds
    start_timestamp = int(pd.Timestamp(start_date).timestamp())
    end_timestamp = int(pd.Timestamp(end_date).timestamp())

    half_hour_interval = 1800  # 30 minutes in seconds
    all_data = []

    current_timestamp = start_timestamp
    while current_timestamp < end_timestamp:
        next_timestamp = current_timestamp + half_hour_interval
        url = f"https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range?vs_currency=usd&from={current_timestamp}&to={next_timestamp}"

        try:
            response = requests.get(url)
            if response.status_code == 429:  # Handle rate limit error
                print(f"Rate limit exceeded. Waiting for 5 seconds...")
                time.sleep(5)  # Wait for 5 seconds before retrying
                continue
            
            response.raise_for_status()  # Raise an exception for other HTTP errors
            data = response.json()

            if 'prices' in data:
                for price_data in data['prices']:
                    timestamp = price_data[0]
                    price = price_data[1]
                    date = pd.to_datetime(timestamp // 1000, unit='s')
                    all_data.append({'Timestamp': date, 'Price': price})

            current_timestamp = next_timestamp
        except Exception as e:
            print(f"Error fetching Ethereum data for timestamp {current_timestamp}: {e}")
            break

    if all_data:
        df = pd.DataFrame(all_data)
        df = df[(df['Timestamp'] >= pd.Timestamp(start_date)) & (df['Timestamp'] <= pd.Timestamp(end_date))]
        return df
    else:
        print("No data available for the specified date range.")
        return None

# Example usage:
start_date = pd.Timestamp.now() - pd.Timedelta(days=2)  # Start date is 2 days ago
end_date = pd.Timestamp.now()  # End date is now

ethereum_half_hourly_data = get_ethereum_half_hourly_data(start_date, end_date)
if ethereum_half_hourly_data is not None:
    print(ethereum_half_hourly_data.head())

    # Save the data to a CSV file
    filename = 'ethereum_half_hourly_historical_data_2_days.csv'
    ethereum_half_hourly_data.to_csv(filename, index=False, mode='a', header=False)