import threading
import time
import logging
import datetime
from binance import Client, ThreadedWebsocketManager, BinanceAPIException
from . import config
from . import indicators

logger = logging.getLogger("MarketDataManager")

class MarketDataManager:
    """
    Centralized manager for all market data.
    Uses WebSockets for real-time price streaming (low weight).
    Caches historical data and account balances (high weight).
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.client = Client(config.API_KEY, config.API_SECRET, tld='us')
        self.twm = ThreadedWebsocketManager(api_key=config.API_KEY, api_secret=config.API_SECRET, tld='us')
        self.twm.start()

        # Cache: {symbol: price}
        self.prices = {}
        self.streams = {} # {symbol: stream_name}
        
        # Cache for REST fallback prices (weight-saving during startup)
        # {symbol: {"price": 0.0, "timestamp": 0}}
        self.prices_rest_cache = {}
        self.prices_rest_ttl = 5 # 5 seconds
        
        # Cache: {symbol: {"volatility": 0.0, "timestamp": 0}}
        self.market_cache = {}
        
        # Cache for Account Balances (weight 20)
        self.account_cache = None
        self.last_account_fetch = 0
        self.account_cache_duration = 30 # 30 seconds

        # Rate Limit tracking
        self.request_weight_minute = 0
        self.last_weight_reset = time.time()
        
        logger.info("MarketDataManager initialized with WebSockets.")

    def _add_weight(self, weight):
        """Track Binance API weight usage."""
        now = time.time()
        if now - self.last_weight_reset > 60:
            self.request_weight_minute = 0
            self.last_weight_reset = now
        self.request_weight_minute += weight
        if self.request_weight_minute > 1000:
            logger.warning(f"⚠️ High request weight detected: {self.request_weight_minute}/1200")

    def start_symbol(self, symbol):
        """Start a WebSocket stream for the given symbol."""
        with self._lock:
            if symbol not in self.streams:
                logger.info(f"Starting WebSocket stream for {symbol}")
                stream_name = self.twm.start_symbol_ticker_socket(
                    callback=self._handle_socket_message,
                    symbol=symbol
                )
                self.streams[symbol] = stream_name

    def stop_symbol(self, symbol):
        """Stop a WebSocket stream for the given symbol."""
        with self._lock:
            if symbol in self.streams:
                logger.info(f"Stopping WebSocket stream for {symbol}")
                self.twm.stop_socket(self.streams[symbol])
                del self.streams[symbol]

    def _handle_socket_message(self, msg):
        """Process incoming WebSocket ticker messages."""
        try:
            if msg['e'] == '24hrTicker':
                symbol = msg['s']
                price = float(msg['c'])
                self.prices[symbol] = price
        except Exception as e:
            logger.error(f"Error handling socket message: {e}")

    def get_price(self, symbol):
        """Get the latest price for a symbol (preferring WebSocket cache)."""
        if symbol in self.prices:
            return self.prices[symbol]
        
        # Check REST cache for this symbol (save weight during startup)
        now = time.time()
        if symbol in self.prices_rest_cache:
            entry = self.prices_rest_cache[symbol]
            if now - entry['timestamp'] < self.prices_rest_ttl:
                return entry['price']
        
        # Fallback to REST if stream hasn't started or reached us yet
        self.start_symbol(symbol)
        try:
            self._add_weight(1)
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            self.prices[symbol] = price
            self.prices_rest_cache[symbol] = {"price": price, "timestamp": now}
            return price
        except Exception as e:
            logger.error(f"REST fallback price fetch failed for {symbol}: {e}")
            return None

    def get_all_prices(self):
        """Fetches all tickers via REST to prime the cache (Weight 40)."""
        try:
            self._add_weight(40)
            tickers = self.client.get_all_tickers()
            for t in tickers:
                self.prices[t['symbol']] = float(t['price'])
            return self.prices
        except Exception as e:
            logger.error(f"Error fetching all tickers: {e}")
            return self.prices

    def get_market_status(self, symbol):
        """Fetches Price and Volatility with caching (weight reduction)."""
        cache_key = symbol
        now = time.time()
        
        # Check cache (1 hour for volatility)
        if cache_key in self.market_cache:
            entry = self.market_cache[cache_key]
            if now - entry['timestamp'] < 3600:
                price = self.get_price(symbol)
                return {
                    "symbol": symbol,
                    "price": price,
                    "volatility": entry['volatility']
                }

        # Fetch fresh data
        try:
            price = self.get_price(symbol)
            # get_historical_klines is weight 1
            self._add_weight(1)
            klines = self.client.get_historical_klines(symbol, Client.KLINE_INTERVAL_1DAY, "14 day ago UTC")
            atr = indicators.calculate_volatility_from_klines(klines, 14)
            volatility = atr / price if price else 0
            
            self.market_cache[cache_key] = {
                "volatility": volatility,
                "timestamp": now
            }
            
            return {
                "symbol": symbol,
                "price": price,
                "volatility": volatility
            }
        except Exception as e:
            logger.error(f"Error fetching market status for {symbol}: {e}")
            return None

    def get_account_info(self, force=False):
        """Fetches account info with 30s caching (saves weight 20)."""
        now = time.time()
        if not force and self.account_cache and (now - self.last_account_fetch < self.account_cache_duration):
            return self.account_cache

        try:
            self._add_weight(20)
            info = self.client.get_account()
            self.account_cache = info
            self.last_account_fetch = now
            return info
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            return None

    def shutdown(self):
        """Cleanly close WebSocket manager."""
        logger.info("Shutting down MarketDataManager...")
        self.twm.stop()

# Global Singleton
market_data_manager = MarketDataManager()
