from collections import deque
import logging
from . import config
from . import indicators
from . import logger_setup

# Logger for strategy decisions
strategy_logger = logging.getLogger("Strategy")

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
                 trading_fee_percentage=0.001,
                 use_trailing_stop=True,
                 dca_enabled=False,
                 dca_rsi_threshold=30):
                 
        self.stop_loss_percent = stop_loss_percent
        self.sell_percent = sell_percent  # Also used as trailing stop distance
        self.fixed_stop_loss_percent = fixed_stop_loss_percent
        self.volatility_period = volatility_period
        
        # Use config defaults if not provided
        self.ma_fast_period = ma_fast_period if ma_fast_period else config.DEFAULT_MA_FAST_PERIOD
        self.ma_slow_period = ma_slow_period if ma_slow_period else config.DEFAULT_MA_SLOW_PERIOD
        self.ma_trend_period = ma_trend_period  # 200 MA for trend filter
        self.rsi_threshold_buy = rsi_threshold_buy
        self.trading_fee_percentage = trading_fee_percentage
        self.use_trailing_stop = use_trailing_stop
        
        # DCA Config
        self.dca_enabled = dca_enabled
        self.dca_rsi_threshold = dca_rsi_threshold
        
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

        # 1. TREND FILTER: Only buy in uptrends OR deep oversold bounces
        # If we don't have enough data for 200 MA, skip trend filter
        trend_is_bullish = True
        
        # EXCEPTION: If RSI is extremely low (e.g. < 33), buy for a bounce even in downtrend
        is_deep_dip = rsi < 33
            
        if ma_trend is not None:
            trend_is_bullish = current_price > ma_trend
            
            if not trend_is_bullish and not is_deep_dip:
                # logger_setup.log_strategy(f"📉 BUY REJECTED: Trend filter failed. Price ${current_price:.2f} < MA200 ${ma_trend:.2f} (RSI={rsi:.1f})")
                return False

        # 2. RSI CHECK: Buy when not overbought
        if rsi >= self.rsi_threshold_buy:
            # logger_setup.log_strategy(f"📉 BUY REJECTED: RSI too high. RSI={rsi:.1f} >= threshold {self.rsi_threshold_buy}")
            return False

        # 3. MACD MOMENTUM FILTER (New)
        # Avoid buying falling knives. Wait for momentum to turn up.
        macd, hist, signal = indicators.calculate_macd(self.price_history)
        if hist is not None:
             # We need previous histogram to check slope. 
             # Re-calc matches current bar. We can just check if Hist > 0 (Uptrend) or check slope if we had history.
             # Since we don't store historical MACD easily without recalculating everything...
             # Let's trust pandas_ta to run on the whole series. 
             # Actually, calculate_macd runs on the series. We can get the *previous* value by slicing the series -1.
             # BUT calculate_macd returns scalar.
             # Let's modify usage: To start simple, just require Histogram > 0 OR (RSI < 25 typically means huge crash, maybe we skip MACD there?)
             # Better: Strict filter -> Histogram must be increasing (Hist > Prev_Hist).
             # To do this efficienty, we really should assume we are at the "end". 
             # For now, let's just use a simple Histogram check: 
             # If Histogram is VERY negative, DON'T BUY.
             
             # Actually, simpler logic:
             # If Histogram < 0 and Histogram < Signal (or just Histogram is decreasing? We don't know prev).
             # Let's just stick to: If MACD Line < Signal Line (Hist < 0) AND RSI > 30, DON'T BUY.
             # (i.e. Only buy normally if MACD is bullish. If MACD Bearish, requires Deep Dip RSI < 30).
             
             if hist < 0 and rsi > 30 and not is_deep_dip:
                 # MACD Bearish (Momentum down) AND RSI not super low. Wait.
                 # logger_setup.log_strategy(f"📉 BUY REJECTED: MACD bearish. Histogram={hist:.4f} < 0, RSI={rsi:.1f}")
                 return False

        # 4. MA CROSS: Short-term bullish momentum
        if ma_fast <= ma_slow:
            # logger_setup.log_strategy(f"📉 BUY REJECTED: MA cross bearish. FastMA={ma_fast:.2f} <= SlowMA={ma_slow:.2f}")
            return False

        # All conditions met!
        trend_str = f"{ma_trend:.2f}" if ma_trend else "N/A"
        macd_str = f"{hist:.4f}" if hist is not None else "N/A"
        
        # Log the signal
        import logging
        logger = logging.getLogger("BinanceTradingBot")
        logger.info(f"*** BUY SIGNAL! RSI={rsi:.2f}, MACD_Hist={macd_str}, FastMA={ma_fast:.2f}, SlowMA={ma_slow:.2f}, TrendMA={trend_str} ***")
        
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
        # FEE PROTECTION: Only activate trailing stop if we are above Break-Even
        # Break Even = Bought Price + 2x Fee (Buy fee + Sell fee)
        break_even_price = bought_price * (1 + 2 * self.trading_fee_percentage)
        
        if self.use_trailing_stop and self.peak_price_since_buy > break_even_price:
            # Only activate trailing stop once we're in REAL profit (net of fees)
            trail_distance = self.sell_percent  # Use sell_percent as trailing distance
            trailing_stop_price = self.peak_price_since_buy * (1 - trail_distance)
            
            # Calculate how close we are to selling
            drop_from_peak = (self.peak_price_since_buy - current_price) / self.peak_price_since_buy
            drop_needed = trail_distance
            closeness = (drop_from_peak / drop_needed) * 100 if drop_needed > 0 else 0
            
            # Log near-misses (>70% of way to trailing stop)
            # if closeness > 70 and closeness < 100:
            #     profit_pct = ((current_price - bought_price) / bought_price) * 100
            #     logger_setup.log_strategy(f"⚠️ NEAR-MISS SELL: {closeness:.0f}% to trailing stop. Profit={profit_pct:.1f}%, Peak=${self.peak_price_since_buy:.2f}")
            
            # Make sure trailing stop is above entry (lock in some profit)
            # Actually, if we are trailing, we respect the trail.
            if current_price < trailing_stop_price:
                profit_pct = ((current_price - bought_price) / bought_price) * 100
                logger_setup.log_strategy(f"✅ TRAILING STOP triggered at ${current_price:.2f} (Peak: ${self.peak_price_since_buy:.2f}, Profit: {profit_pct:.1f}%)")
                print(f"*** TRAILING STOP triggered at {current_price:.2f} (Peak: {self.peak_price_since_buy:.2f}, BreakEven: {break_even_price:.2f}) ***")
                self.reset_trailing_stop()
                return 'SELL'

        # 2. HARD STOP LOSS (below entry - protects capital)
        # Use simple fixed % logic now that settings are auto-tuned externally
        sl_percent = self.fixed_stop_loss_percent
            
        stop_loss_price = bought_price * (1 - sl_percent)
        
        if current_price < stop_loss_price:
            print(f"*** STOP LOSS triggered at {current_price:.2f} (Entry: {bought_price:.2f}, SL: {stop_loss_price:.2f}) ***")
            self.reset_trailing_stop()
            return 'STOP_LOSS'


        return None

    def check_dca_signal(self, current_price, bought_price):
        """
        Checks if we should buy more (Avg Down) instead of Sell.
        Trigger: Price < Bought (-2%) AND RSI < Threshold (30)
        """
        if not self.dca_enabled:
            return False
            
        # 1. Price Check: Must be significantly lower than entry (e.g., -2% min)
        # Prevents buying on tiny volatility
        if current_price > bought_price * 0.98:
            return False
            
        # 2. Indicator Check: RSI Oversold
        current_rsi = indicators.calculate_rsi(self.price_history) if len(self.price_history) > 14 else 50
        
        if current_rsi < self.dca_rsi_threshold:
            return True
            
        return False
