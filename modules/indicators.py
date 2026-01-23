import pandas as pd
import pandas_ta as ta

def calculate_rsi(price_series, length=14):
    """Calculates RSI for a given price series."""
    try:
        if len(price_series) < length:  # Not enough data
            return None

        # Convert to Series for pandas_ta
        close_series = pd.Series(list(price_series)) # Ensure it's a list/series
        rsi_indicator = ta.rsi(close_series, length=length)
        if rsi_indicator is None or rsi_indicator.empty:
             return None
             
        return rsi_indicator.iloc[-1] # Return the latest RSI value

    except Exception as e:
        # Caller handles logging
        raise e

def calculate_macd(price_series, fast=12, slow=26, signal=9):
    """Calculates MACD, Signal, and Histogram."""
    try:
        if len(price_series) < slow + signal:
            return None, None, None
            
        close_series = pd.Series(list(price_series))
        macd_df = ta.macd(close_series, fast=fast, slow=slow, signal=signal)
        
        if macd_df is None or macd_df.empty:
            return None, None, None
            
        # pandas_ta returns columns like: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        # We need the last values
        last_row = macd_df.iloc[-1]
        
        # Try finding columns dynamically to be safe
        # MACD line usually starts with MACD_
        # Histogram usually starts with MACDh_
        # Signal usually starts with MACDs_
        
        cols = macd_df.columns
        macd_col = next((c for c in cols if c.startswith(f"MACD_{fast}_{slow}")), None)
        hist_col = next((c for c in cols if c.startswith(f"MACDh_{fast}_{slow}")), None)
        sig_col  = next((c for c in cols if c.startswith(f"MACDs_{fast}_{slow}")), None)
        
        if not macd_col or not hist_col or not sig_col:
             # Fallback to positional if naming fails 
             # (Assume: 0=MACD, 1=Hist, 2=Signal based on standard pandas_ta output)
             macd_val = macd_df.iloc[-1, 0]
             hist_val = macd_df.iloc[-1, 1]
             sig_val  = macd_df.iloc[-1, 2]
        else:
             macd_val = last_row[macd_col]
             hist_val = last_row[hist_col]
             sig_val  = last_row[sig_col]

        return macd_val, hist_val, sig_val
        
    except Exception as e:
        print(f"Error calculating MACD: {e}")
        return None, None, None

def calculate_volatility_from_klines(klines, period=14):
    """
    Calculates the 14-day Average True Range (ATR) from Klines.
    klines should be a list of lists/tuples from Binance API.
    """
    try:
        if len(klines) <= 1:
            return 0.0
            
        atr = 0.0
        num_bars = len(klines) - 1  # Number of True Range calculations
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            prev_close = float(klines[i-1][4])
            
            tr = max(
                abs(high - low),             # Current High - Current Low
                abs(high - prev_close),      # Current High - Previous Close
                abs(low - prev_close)        # Current Low - Previous Close
            )
            atr += tr
        atr /= num_bars  # FIX: Divide by actual number of bars, not period
        return atr
    except Exception as e:
        raise e

def get_dynamic_stop_loss_percent(volatility, base_sl=0.01, multiplier=0.1):
    """Determines the stop-loss percentage based on volatility."""
    if volatility is None:
        return base_sl
    return base_sl + (volatility * multiplier)

def calculate_ma(price_series, period):
    """Calculates Simple Moving Average (SMA)."""
    if len(price_series) < period:
        return None
    return sum(list(price_series)[-period:]) / period

def calculate_average_volume(volume_series, period=20):
    """Calculates the average volume over a period."""
    if len(volume_series) < period:
        return None
    return sum(list(volume_series)[-period:]) / period

def is_volume_confirmed(current_volume, avg_volume, multiplier=1.2):
    """
    Checks if current volume is above average (confirmation of strong move).
    
    Args:
        current_volume: Current bar's volume
        avg_volume: Average volume over recent period
        multiplier: How many times average volume is required (default 1.2x)
    
    Returns:
        True if volume is confirmed (above threshold), False otherwise
    """
    if avg_volume is None or avg_volume == 0:
        return True  # No data, allow trade
    return current_volume >= (avg_volume * multiplier)

def calculate_higher_timeframe_trend(klines, ma_period=50):
    """
    Analyzes higher timeframe (e.g., 4H) to determine trend direction.
    
    Args:
        klines: List of kline data from Binance API
        ma_period: Moving average period for trend detection
    
    Returns:
        dict with 'trend' ('bullish', 'bearish', 'neutral'), 'ma_value', 'current_price'
    """
    try:
        if not klines or len(klines) < ma_period:
            return {'trend': 'neutral', 'ma_value': None, 'current_price': None}
        
        # Extract close prices
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1]
        
        # Calculate MA
        ma_value = sum(closes[-ma_period:]) / ma_period
        
        # Determine trend
        if current_price > ma_value * 1.01:  # 1% above MA = bullish
            trend = 'bullish'
        elif current_price < ma_value * 0.99:  # 1% below MA = bearish
            trend = 'bearish'
        else:
            trend = 'neutral'
        
        return {
            'trend': trend,
            'ma_value': ma_value,
            'current_price': current_price
        }
    except Exception as e:
        print(f"Error calculating higher timeframe trend: {e}")
        return {'trend': 'neutral', 'ma_value': None, 'current_price': None}

