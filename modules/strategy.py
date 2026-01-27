from collections import deque
import logging
import time
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
                 dca_rsi_threshold=30,
                 # New: Advanced features
                 volume_confirmation_enabled=True,
                 volume_multiplier=1.2,
                 multi_timeframe_enabled=True,
                 cooldown_after_stoploss_minutes=30,
                 # New: Manual Control Features
                 missed_trade_log_enabled=True,
                 support_resistance_check_enabled=False,
                 ml_confirmation_enabled=False,
                 order_book_check_enabled=False,
                 # Phase 3: Advanced Trading
                 ttp_activation_pct=0.015,
                 ttp_callback_pct=0.005,
                 dca_max_levels=5,
                 dca_multiplier=1.5):
                 
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
        self.volume_history = deque(maxlen=30)  # NEW: Volume tracking
        self.current_volatility = None
        
        # Trailing stop tracking
        self.peak_price_since_buy = None
        
        # NEW: Advanced feature settings
        self.volume_confirmation_enabled = volume_confirmation_enabled
        self.volume_multiplier = volume_multiplier
        self.multi_timeframe_enabled = multi_timeframe_enabled
        self.cooldown_after_stoploss_minutes = cooldown_after_stoploss_minutes
        
        # NEW feature flags
        self.missed_trade_log_enabled = missed_trade_log_enabled
        self.support_resistance_check_enabled = support_resistance_check_enabled
        self.ml_confirmation_enabled = ml_confirmation_enabled
        self.order_book_check_enabled = order_book_check_enabled
        
        # New Phase 3 Attributes
        self.ttp_activation_pct = ttp_activation_pct
        self.ttp_callback_pct = ttp_callback_pct
        self.dca_max_levels = dca_max_levels
        self.dca_multiplier = dca_multiplier
        self.ttp_active = False # Flag to indicate if trailing has started
        
        # External modules/data placeholders
        self.ml_predictor = None
        self.current_support = None
        self.current_resistance = None
        
        # NEW: State for cooldown tracking
        self.last_stoploss_time = None
        
        # NEW: Higher timeframe trend cache
        self.higher_tf_trend = None
        self.higher_tf_last_update = None
        
        # Log throttling state
        self.last_trend_log_time = 0
        self.last_rejection_reason = None
        
        # Phase 5: Sentiment Analysis
        self.sentiment_enabled = False # Default off, user enables in Config
        self.sentiment_threshold = 0.0 # Neutral or better
        
        from .sentiment_analyzer import SentimentAnalyzer
        self.sentiment_analyzer = SentimentAnalyzer()

    def set_ml_predictor(self, predictor):
        """Sets the ML predictor instance."""
        self.ml_predictor = predictor

    def set_support_resistance(self, support, resistance):
        """Updates current support/resistance levels."""
        self.current_support = support
        self.current_resistance = resistance

    def log_missed_trade(self, price, reason):
        """Logs rejected signals if enabled."""
        if self.missed_trade_log_enabled:
             # Only log if reason changed to avoid spamming the log every second
             if self.last_rejection_reason != reason:
                 # Clean reason string for log
                 clean_reason = reason.replace('\n', ' ')
                 logger_setup.log_strategy(f"📉 MISSED TRADE: {clean_reason} | Price: ${price:.2f}")
                 self.last_rejection_reason = reason  # Update reason to prevent spam
        
    def update_data(self, price, volume=None):
        """Adds a new price point (and optionally volume) to history."""
        if price is not None:
            self.price_history.append(price)
        if volume is not None:
            self.volume_history.append(volume)

    def update_volume(self, volume):
        """Adds a new volume data point."""
        if volume is not None:
            self.volume_history.append(volume)

    def set_volatility(self, value):
        """Updates the current market volatility (ATR)."""
        self.current_volatility = value
    
    def set_higher_timeframe_trend(self, trend_data):
        """Updates the cached higher timeframe trend."""
        self.higher_tf_trend = trend_data
        self.higher_tf_last_update = time.time()
    
    def record_stoploss(self):
        """Records the time of a stop-loss event for cooldown tracking."""
        self.last_stoploss_time = time.time()
        
    def is_in_cooldown(self):
        """
        Checks if we're still in cooldown period after a stop-loss.
        Returns True if we should NOT trade yet.
        """
        if self.last_stoploss_time is None:
            return False
        
        elapsed_minutes = (time.time() - self.last_stoploss_time) / 60
        return elapsed_minutes < self.cooldown_after_stoploss_minutes
    
    def get_cooldown_remaining(self):
        """Returns remaining cooldown time in minutes, or 0 if not in cooldown."""
        if self.last_stoploss_time is None:
            return 0
        elapsed_minutes = (time.time() - self.last_stoploss_time) / 60
        remaining = self.cooldown_after_stoploss_minutes - elapsed_minutes
        return max(0, remaining)
    
    def check_volume_confirmation(self, current_volume):
        """
        Checks if current volume confirms a strong signal.
        Returns True if volume is above average (or feature disabled).
        """
        if not self.volume_confirmation_enabled:
            return True
        
        avg_volume = indicators.calculate_average_volume(self.volume_history)
        return indicators.is_volume_confirmed(current_volume, avg_volume, self.volume_multiplier)
    
    def check_higher_timeframe_trend(self):
        """
        Checks if higher timeframe trend is bullish.
        Returns True if bullish or neutral, False if bearish.
        """
        if not self.multi_timeframe_enabled:
            return True  # Feature disabled, allow entry
        
        if self.higher_tf_trend is None:
            return True  # No data yet, allow entry
        
        # Allow entry in bullish or neutral trends
        return self.higher_tf_trend.get('trend') != 'bearish'
        
    def reset_trailing_stop(self):
        """Resets the trailing stop peak tracker (call after selling)."""
        self.peak_price_since_buy = None
        self.ttp_active = False

    def check_buy_signal(self, current_price, last_price, current_volume=None):
        """
        Determines if a buy signal is generated based on:
        - COOLDOWN: Skip if recently stopped out
        - MULTI-TIMEFRAME: 4H trend must be bullish/neutral
        - VOLUME: Current volume must be above average
        - Trend Filter: Price above 200 MA (bullish trend)
        - RSI < 40 (oversold/neutral, opportunity to buy)
        - MA Cross: Fast MA > Slow MA (short-term momentum)
        
        Returns: True if buy signal, False otherwise
        """
        if current_price is None:
            return False

        # Calculate indicators early
        rsi = indicators.calculate_rsi(self.price_history)
        
        # Define "Deep Dip" condition (RSI < 30) to bypass trend filters
        # This allows catching "major dips" even if the 4H trend is bearish
        is_deep_dip = rsi is not None and rsi < 30

        # ===== NEW FILTER #1: COOLDOWN AFTER STOP-LOSS =====
        if self.is_in_cooldown():
            remaining = self.get_cooldown_remaining()
            # Only log occasionally to avoid spam
            # logger_setup.log_strategy(f"⏳ COOLDOWN: {remaining:.1f} min remaining after stop-loss")
            return False
        
        # ===== NEW FILTER #2: MULTI-TIMEFRAME TREND =====
        # MODIFIED: Allow buying if it's a "Deep Dip" (RSI < 30) regardless of trend
        if not is_deep_dip and not self.check_higher_timeframe_trend():
            htf = self.higher_tf_trend
            if htf:
                 # Throttle Logging: Only log if significant time passed or reason changed
                 current_time = time.time()
                 reason_key = f"trend_bearish_{htf.get('ma_value', 0)}"
                 
                 if (current_time - self.last_trend_log_time > 900) or (self.last_rejection_reason != reason_key):
                     logger_setup.log_strategy(f"📉 BUY REJECTED: 4H trend is BEARISH (MA50: ${htf.get('ma_value', 0):.2f})")
                     self.last_trend_log_time = current_time
                     self.last_rejection_reason = reason_key
            return False
        
        # ===== NEW FILTER #3: VOLUME CONFIRMATION =====
        if current_volume is not None and not self.check_volume_confirmation(current_volume):
            avg_vol = indicators.calculate_average_volume(self.volume_history)
            if avg_vol:
                needed = avg_vol * self.volume_multiplier
                # logger_setup.log_strategy(f"📉 BUY REJECTED: Low volume ({current_volume:.0f} < {needed:.0f} required)")
            return False
            
        # ===== NEW FILTER #4: SENTIMENT ANALYSIS =====
        if self.sentiment_enabled:
            score = self.sentiment_analyzer.get_sentiment_score()
            if score < self.sentiment_threshold:
                 # Throttle Log
                 current_time = time.time()
                 if (current_time - self.last_trend_log_time > 900):
                     logger_setup.log_strategy(f"📉 BUY REJECTED: Sentiment Bearish ({score:.2f} < {self.sentiment_threshold})")
                     self.last_trend_log_time = current_time
                 return False

        # Calculate remaining indicators
        ma_fast = indicators.calculate_ma(self.price_history, self.ma_fast_period)
        ma_slow = indicators.calculate_ma(self.price_history, self.ma_slow_period)
        ma_trend = indicators.calculate_ma(self.price_history, self.ma_trend_period)
        # RSI already calculated above

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
                self.last_rejection_reason = f"Trend Bearish (Must be > ${ma_trend:.2f})"
                return False

        # 2. RSI CHECK: Buy when not overbought
        if rsi >= self.rsi_threshold_buy:
            self.last_rejection_reason = f"RSI Too High ({rsi:.1f} >= {self.rsi_threshold_buy})"
            return False

        # 3. MACD MOMENTUM FILTER (New)
        macd, hist, signal = indicators.calculate_macd(self.price_history)
        if hist is not None:
             if hist < 0 and rsi > 30 and not is_deep_dip:
                 self.last_rejection_reason = f"MACD Bearish (Hist {hist:.4f} < 0)"
                 return False

        # 4. MA CROSS: Short-term bullish momentum
        if ma_fast <= ma_slow:
            self.last_rejection_reason = f"MA Cross Bearish (Fast ${ma_fast:.2f} <= Slow ${ma_slow:.2f})"
            return False

        # All conditions met!
        self.last_rejection_reason = "BUYING NOW"
        trend_str = f"{ma_trend:.2f}" if ma_trend else "N/A"
        macd_str = f"{hist:.4f}" if hist is not None else "N/A"
        
        # Build extra confirmation string
        extra_conf = ""
        if self.ml_confirmation_enabled and self.ml_predictor:
             # Calculate features for ML
             # Use current RSI, Volatility, and the new slope/ratio indicators
             ma_fast_list = [indicators.calculate_ma(list(self.price_history)[:i], self.ma_fast_period) for i in range(-5, 0)]
             ma_fast_list = [m for m in ma_fast_list if m is not None]
             
             features = {
                 'rsi': rsi,
                 'volatility': self.current_volatility or 0.0,
                 'volume_ratio': indicators.calculate_volume_ratio(self.volume_history, current_volume) if current_volume else 1.0,
                 'fast_ma_slope': indicators.calculate_slope(ma_fast_list) if len(ma_fast_list) >= 2 else 0.0
             }
             
             win_prob = self.ml_predictor.predict_quality(features)
             if win_prob < 0.5:
                 self.last_rejection_reason = f"ML Rejected (Win Prob: {win_prob:.2f} < 0.5)"
                 return False
                 
             extra_conf += f" | ML: PASS ({win_prob:.2f}) "
        if self.support_resistance_check_enabled:
             extra_conf += " | S/R: Safe "

        # Log the signal
        strategy_logger.info(f"*** BUY SIGNAL! RSI={rsi:.2f}, MACD_Hist={macd_str}, FastMA={ma_fast:.2f}, TrendMA={trend_str}{extra_conf} ***")
        
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

        # 1. TRAiling TAKE PROFIT (TTP)
        profit_pct = ((current_price - bought_price) / bought_price)
        break_even_price = bought_price * (1 + 2 * self.trading_fee_percentage)
        
        # Check if we should activate TTP (only if we are above activation threshold AND above break-even)
        if not self.ttp_active and current_price > break_even_price:
            if profit_pct >= self.ttp_activation_pct:
                self.ttp_active = True
                self.peak_price_since_buy = current_price
                logger_setup.log_strategy(f"🔥 TTP ACTIVATED at {current_price:.2f} (+{profit_pct*100:.2f}%)")

        if self.ttp_active:
            # Update peak
            if current_price > self.peak_price_since_buy:
                self.peak_price_since_buy = current_price
                # self.logger.debug(f"New Peak: {self.peak_price_since_buy}")

            # Calculate trailing stop price
            trailing_stop_price = self.peak_price_since_buy * (1 - self.ttp_callback_pct)
            
            if current_price < trailing_stop_price:
                final_profit = ((current_price - bought_price) / bought_price) * 100
                logger_setup.log_strategy(f"✅ TTP TRIGGERED at ${current_price:.2f} (Peak: ${self.peak_price_since_buy:.2f}, Profit: {final_profit:.2f}%)")
                self.reset_trailing_stop()
                return 'SELL'

        # Legacy Trailing Stop (Fallback/Alternative use)
        # If TTP isn't active, but we have use_trailing_stop enabled for general protection
        elif self.use_trailing_stop and current_price > break_even_price:
            # Standard logic (follows from entry)
            trail_distance = self.sell_percent
            trailing_stop_price = self.peak_price_since_buy * (1 - trail_distance)
            if current_price < trailing_stop_price:
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
