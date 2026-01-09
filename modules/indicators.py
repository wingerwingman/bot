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

def calculate_volatility_from_klines(klines, period=14):
    """
    Calculates the 14-day Average True Range (ATR) from Klines.
    klines should be a list of lists/tuples from Binance API.
    """
    try:
        if len(klines) <= 1:
            return 0.0
            
        atr = 0.0
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
        atr /= period
        return atr
    except Exception as e:
        raise e

def get_dynamic_stop_loss_percent(volatility, base_sl=0.01, multiplier=0.1):
    """Determines the stop-loss percentage based on volatility."""
    if volatility is None:
        return base_sl
    return base_sl + (volatility * multiplier)
