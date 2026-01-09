from binance import Client
import os
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv('BINANCE_US_API_KEY')
api_secret = os.getenv('BINANCE_US_API_SECRET')
client = Client(api_key, api_secret, tld='us') # Using an arbitrary offset for testing.

try:
    print(client.get_server_time())  # Basic API call to check connectivity
except Exception as e:
    print(f"Error: {e}")