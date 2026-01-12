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
    
    url = f"https://min-api.cryptocompare.com/data/v2/histohour?fsym=SOL&tsym=USD&limit=10000&toTs={end_timestamp}&e=binance"
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        data = response.json()
        
        if 'Data' in data and 'Data' in data['Data']:
            # Extract date-price pairs from the response
            data = data['Data']['Data']
            dates = [pd.to_datetime(entry['time'], unit='s') for entry in data]
            prices = [entry['close'] for entry in data]
            
            df = pd.DataFrame({'Date': dates, 'Price': prices})
            
            # Filter data based on the start and end date
            df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
            
            return df
        else:
            print("Response data format is unexpected:")
            print(data)
            return None

    except Exception as e:
        print("Error fetching Solana hourly data:", e)
        return None

# Example usage:
start_date = pd.Timestamp.now() - pd.Timedelta(weeks=4)  # Start date is 4 weeks ago
end_date = pd.Timestamp.now()  # End date is now
solana_hourly_data = get_solana_hourly_data(start_date, end_date)

if solana_hourly_data is not None:
    print(solana_hourly_data.head())
    # Save the data to a CSV file
    filename = 'solana_hourly_historical_data_4_weeks.csv'
    solana_hourly_data.to_csv(filename, index=False)