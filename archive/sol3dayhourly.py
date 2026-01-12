import pandas as pd
import requests
import time

def get_solana_hourly_data(start_date, end_date):
    """
    Get Solana (SOL) hourly price data from CryptoCompare API.

    Parameters:
    - start_date: Start date of the data (string in 'YYYY-MM-DD' format)
    - end_date: End date of the data (string in 'YYYY-MM-DD' format)

    Returns:
    - DataFrame containing Solana (SOL) hourly price data
    """
    # Convert start_date and end_date to Unix timestamps in seconds
    start_timestamp = int(pd.Timestamp(start_date).timestamp())
    end_timestamp = int(pd.Timestamp(end_date).timestamp())

    hour_interval = 3600  # 1 hour in seconds

    all_data = []

    current_timestamp = start_timestamp
    while current_timestamp < end_timestamp:
        next_timestamp = current_timestamp + hour_interval
        url = f"https://min-api.cryptocompare.com/data/v2/histohour?fsym=SOL&tsym=USD&limit=1&toTs={next_timestamp}&e=binance"

        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
            data = response.json()

            if 'Data' in data and 'Data' in data['Data']:
                # Extract date-price pair from the response
                entry = data['Data']['Data'][0]
                date = pd.to_datetime(entry['time'], unit='s')
                price = entry['close']
                all_data.append({'Date': date, 'Price': price})

            current_timestamp = next_timestamp
        except Exception as e:
            print(f"Error fetching Solana data for timestamp {current_timestamp}: {e}")
            break

    df = pd.DataFrame(all_data)
    df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
    return df

# Example usage:
start_date = pd.Timestamp.now() - pd.Timedelta(days=3)  # Start date is 3 days ago
end_date = pd.Timestamp.now()  # End date is now

solana_hourly_data = get_solana_hourly_data(start_date, end_date)
if solana_hourly_data is not None:
    print(solana_hourly_data.head())

    # Save the data to a CSV file
    filename = 'solana_hourly_historical_data_3_days.csv'
    solana_hourly_data.to_csv(filename, index=False)