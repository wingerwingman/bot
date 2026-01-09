import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Credentials
API_KEY = os.getenv('BINANCE_US_API_KEY')
API_SECRET = os.getenv('BINANCE_US_API_SECRET')

# File Names
TRADING_LOG_FILE = 'logs/trading_us.log'
TRADE_LOG_FILE = 'logs/trades_us.log'

# Trading Defaults
DEFAULT_MA_FAST_PERIOD = 7
DEFAULT_MA_SLOW_PERIOD = 25
DEFAULT_VOLATILITY_PERIOD = 14
