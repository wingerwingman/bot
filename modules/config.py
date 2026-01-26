import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Credentials
API_KEY = os.getenv('BINANCE_US_API_KEY')
API_SECRET = os.getenv('BINANCE_US_API_SECRET')

# Admin Credentials
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS') # No default for security
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN')

# Telegram Notifications
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Sentiment Analysis
CRYPTOPANIC_API_KEY = os.getenv('CRYPTOPANIC_API_KEY')

# File Names
TRADING_LOG_FILE = 'logs/trading_us.log'
TRADE_LOG_FILE = 'logs/trades_us.log'
TUNING_LOG_FILE = 'logs/tuning.csv'
STRATEGY_HISTORY_FILE = 'logs/strategy_history.log'
AUDIT_LOG_FILE = 'logs/audit.log'
ERROR_LOG_FILE = 'logs/errors.log'

# Trading Defaults
DEFAULT_MA_FAST_PERIOD = 7
DEFAULT_MA_SLOW_PERIOD = 25
DEFAULT_VOLATILITY_PERIOD = 14

# DCA (Defense Mode) Settings
DCA_ENABLED = True
DCA_MAX_RETRIES = 3      # Max number of safety buys
DCA_RSI_THRESHOLD = 30   # Only buy if RSI drops below this
DCA_SCALE_FACTOR = 1.0   # Buy 1.0x the initial amount (Linear Scaling)

# Advanced Strategy Settings
STOP_LOSS_COOLDOWN_MINUTES = 30   # Wait time after a stop-loss before re-entering
VOLUME_CONFIRMATION_ENABLED = True # Require above-average volume for buy signals
VOLUME_MULTIPLIER_THRESHOLD = 1.2  # Volume must be 1.2x average to confirm
MULTI_TIMEFRAME_ENABLED = True     # Check 4H trend before entry
TREND_TIMEFRAME = '4h'             # Higher timeframe for trend confirmation
TREND_MA_PERIOD = 50               # MA period on higher timeframe

# New Features (Manual Control)
MISSED_TRADE_LOG_ENABLED = True       # Log rejected signals (Imp 4)
ORDER_BOOK_CHECK_ENABLED = False       # Check bid/ask spread (Imp 5) - Default OFF for manual control
ORDER_BOOK_DEPTH_RATIO = 2.0          # Min ratio of Bids to Asks to verify support (Example)
SUPPORT_RESISTANCE_CHECK_ENABLED = False # Avoid buying at resistance (Imp 6) - Default OFF
SUPPORT_RESISTANCE_WINDOW = 50        # Lookback period for finding peaks
ML_CONFIRMATION_ENABLED = False       # Use ML model to confirm signals (Imp 15) - Default OFF
HEATMAP_CALCULATION_ENABLED = True    # Calculate profitability by hour (Imp 8)
