from collections import deque
from . import config
from . import indicators

class Strategy:
    """
    Encapsulates the trading strategy logic.
    Decouples the 'decision making' from the 'execution' (Bot).
    
    Improvements implemented:
    - Trend filter (200 MA)
    - Removed -1% drop requirement
    - Trailing stop loss
    """

    def __init__(self, 
                 stop_loss_percent=0.02, 
                 sell_percent=0.03,  # Now used as trailing stop distance
                 fixed_stop_loss_percent=0.02,
                 volatility_period=14,
                 ma_fast_period=None,
                 ma_slow_period=None,
                 ma_trend_period=200,
                 rsi_threshold_buy=40,  # Raised from 30 for more opportunities
                 use_trailing_stop=True):
                 
        self.stop_loss_percent = stop_loss_percent
        self.sell_percent = sell_percent  # Also used as trailing stop distance
        self.fixed_stop_loss_percent = fixed_stop_loss_percent
        self.volatility_period = volatility_period
        
        # Use config defaults if not provided
        self.ma_fast_period = ma_fast_period if ma_fast_period else config.DEFAULT_MA_FAST_PERIOD
        self.ma_slow_period = ma_slow_period if ma_slow_period else config.DEFAULT_MA_SLOW_PERIOD
        self.ma_trend_period = ma_trend_period  # 200 MA for trend filter
        self.rsi_threshold_buy = rsi_threshold_buy
        self.use_trailing_stop = use_trailing_stop
        
        self.price_history = deque(maxlen=250)  # Increased for 200 MA
        self.current_volatility = None
        
        # Trailing stop tracking
        self.peak_price_since_buy = None
        
    def update_data(self, price):
        """Adds a new price point to history."""
        if price is not None:
            self.price_history.append(price)

    def set_volatility(self, value):
        """Updates the current market volatility (ATR)."""
        self.current_volatility = value
        
    def reset_trailing_stop(self):
        """Resets the trailing stop peak tracker (call after selling)."""
        self.peak_price_since_buy = None

    def check_buy_signal(self, current_price, last_price):
        """
        Determines if a buy signal is generated based on:
        - Trend Filter: Price above 200 MA (bullish trend)
        - RSI < 40 (oversold/neutral, opportunity to buy)
        - MA Cross: Fast MA > Slow MA (short-term momentum)
        
        REMOVED: -1% drop requirement (was too restrictive)
        """
        if current_price is None:
            return False

        # Calculate indicators
        ma_fast = indicators.calculate_ma(self.price_history, self.ma_fast_period)
        ma_slow = indicators.calculate_ma(self.price_history, self.ma_slow_period)
        ma_trend = indicators.calculate_ma(self.price_history, self.ma_trend_period)
        rsi = indicators.calculate_rsi(self.price_history)

        # Ensure we have enough data for all indicators
        if rsi is None or ma_fast is None or ma_slow is None:
            return False

        # 1. TREND FILTER: Only buy in uptrends
        # If we don't have enough data for 200 MA, skip trend filter
        trend_is_bullish = True
        if ma_trend is not None:
            trend_is_bullish = current_price > ma_trend
            if not trend_is_bullish:
                # print(f"Debug: Trend filter failed. Price {current_price:.2f} < MA200 {ma_trend:.2f}")
                return False

        # 2. RSI CHECK: Buy when not overbought
        if rsi >= self.rsi_threshold_buy:
            return False

        # 3. MA CROSS: Short-term bullish momentum
        if ma_fast <= ma_slow:
            return False

        # All conditions met!
        trend_str = f"{ma_trend:.2f}" if ma_trend else "N/A"
        print(f"*** BUY SIGNAL! RSI={rsi:.2f}, FastMA={ma_fast:.2f}, SlowMA={ma_slow:.2f}, TrendMA={trend_str} ***")
        return True

    def check_sell_signal(self, current_price, bought_price):
        """
        Determines if a sell signal is generated.
        
        Uses TRAILING STOP LOSS instead of fixed take-profit:
        - Tracks peak price since buy
        - Sells if price drops X% from peak
        - Also has hard stop-loss below entry
        
        Returns: 'SELL', 'STOP_LOSS', or None
        """
        if bought_price is None:
            return None

        # Update peak price for trailing stop
        if self.peak_price_since_buy is None:
            self.peak_price_since_buy = bought_price
        
        if current_price > self.peak_price_since_buy:
            self.peak_price_since_buy = current_price

        # 1. TRAILING STOP LOSS (replaces fixed take-profit)
        if self.use_trailing_stop and self.peak_price_since_buy > bought_price:
            # Only activate trailing stop once we're in profit
            trail_distance = self.sell_percent  # Use sell_percent as trailing distance
            trailing_stop_price = self.peak_price_since_buy * (1 - trail_distance)
            
            # Make sure trailing stop is above entry (lock in some profit)
            if trailing_stop_price > bought_price and current_price < trailing_stop_price:
                print(f"*** TRAILING STOP triggered at {current_price:.2f} (Peak: {self.peak_price_since_buy:.2f}) ***")
                self.reset_trailing_stop()
                return 'SELL'

        # 2. HARD STOP LOSS (below entry - protects capital)
        sl_percent = self.fixed_stop_loss_percent
        if self.current_volatility is not None:
            sl_percent = indicators.get_dynamic_stop_loss_percent(self.current_volatility, self.stop_loss_percent)
            
        stop_loss_price = bought_price * (1 - sl_percent)
        
        if current_price < stop_loss_price:
            print(f"*** STOP LOSS triggered at {current_price:.2f} (Entry: {bought_price:.2f}, SL: {stop_loss_price:.2f}) ***")
            self.reset_trailing_stop()
            return 'STOP_LOSS'

        return None
