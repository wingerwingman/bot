from collections import deque
import logging
import os
from . import config
recent_errors = deque(maxlen=100)
strategy_logs = deque(maxlen=50) # Strategy Tuning Logs
audit_logs = deque(maxlen=100) # User Operation Audit Trail

class ListHandler(logging.Handler):
    """Custom handler to store logs in a list."""
    def emit(self, record):
        try:
            log_entry = self.format(record)
            recent_errors.appendleft(log_entry) # Newest first
        except Exception:
            self.handleError(record)

def clear_errors():
    """Clears the recent error buffer."""
    recent_errors.clear()

def log_strategy(message):
    """Logs a strategy update message."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    strategy_logs.appendleft(f"{timestamp} - {message}")

def log_audit(action, details, ip_address="Unknown"):
    """
    Log a user operation for the Audit Trail.
    Format: [Timestamp] [IP] [Action] [Details]
    """
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "ip": ip_address,
        "action": action,
        "details": details
    }
    audit_logs.appendleft(entry) # Newest first
    # Also log to system file for permanence
    logging.getLogger("BinanceTradingBot").info(f"AUDIT WARN: User Action [{action}] via {ip_address}: {details}")

def clear_all_logs():
    """Clears both system and strategy logs."""
    recent_errors.clear()
    strategy_logs.clear()

def setup_logger(name="BinanceTradingBot", log_file=config.TRADING_LOG_FILE):
    """Sets up the main logger and the trade-specific logger."""
    
    # 1. Clear log files on startup
    if os.path.exists(config.TRADING_LOG_FILE):
        open(config.TRADING_LOG_FILE, 'w').close()
    if os.path.exists(config.TRADE_LOG_FILE):
        open(config.TRADE_LOG_FILE, 'w').close()

    # 2. Main Logger Setup
    logger = logging.getLogger("BinanceTradingBot")
    logger.setLevel(logging.DEBUG)
    
    # Avoid duplicate handlers if called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fh = logging.FileHandler(config.TRADING_LOG_FILE)  # Main log file
    fh.setLevel(logging.DEBUG)
    
    # List Handler for UI Errors (Only actual errors/warnings, not general info/trades)
    lh = ListHandler()
    lh.setLevel(logging.WARNING)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    lh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.addHandler(lh)

    # 3. Trade Logger Setup
    trade_logger = logging.getLogger("trade_logger")
    trade_logger.setLevel(logging.INFO)
    
    if trade_logger.hasHandlers():
        trade_logger.handlers.clear()
    trade_logger.propagate = False  # Prevent bubbling up to root

    # Ensure no duplicate handlers if called multiple times (though mainly for cleanup)
    if not trade_logger.handlers:
        trade_fh = logging.FileHandler(config.TRADE_LOG_FILE)
        trade_fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
        trade_logger.addHandler(trade_fh)
        
    # 4. Tuning Logger Setup (Persistent detailed metrics)
    tuning_logger = logging.getLogger("tuning_logger")
    tuning_logger.setLevel(logging.INFO)
    tuning_logger.propagate = False
    
    if not tuning_logger.handlers:
        tuning_fh = logging.FileHandler(config.TUNING_LOG_FILE)
        # CSV Header: Timestamp, Symbol, Action, Price, Qty, Profit, Volatility, RangeLow, RangeHigh, Step
        tuning_fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
        tuning_logger.addHandler(tuning_fh)
        
        # Write header if file is empty
        if os.stat(config.TUNING_LOG_FILE).st_size == 0:
            tuning_logger.info("Timestamp,Symbol,Action,Price,Qty,Profit,Volatility,RangeLow,RangeHigh,Step,StepPct")

    return logger, trade_logger

def log_trade(main_logger, trade_logger, action, price, quantity=None, total_value=None, profit=None):
    """
    Helper to log trades to both the specific trade logger and general debug.
    """
    try:
        msg_parts = [str(action), str(quantity), str(price)]
        if total_value is not None:
            msg_parts.append(str(total_value))
        if profit is not None:
            msg_parts.append(f"{profit:.2f}%")
            
        msg = ",".join(msg_parts)
            
        main_logger.info(f"DEBUG: Attempting to log trade: {msg}") 
        trade_logger.info(msg)
        
        # Force flush
        for handler in trade_logger.handlers:
            handler.flush()
            
    except Exception as e:
        main_logger.error(f"Error logging trade: {e}")

def log_tuning(symbol, action, price, qty, profit, volatility, range_low, range_high, step, step_pct):
    """
    Logs detailed tuning metrics to CSV.
    """
    try:
        logger = logging.getLogger("tuning_logger")
        # Ensure handlers exist (lazy init if needed, usually covered by setup)
        if not logger.handlers:
            # Fallback if setup wasn't called or handlers lost
            fh = logging.FileHandler(config.TUNING_LOG_FILE)
            fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
            logger.addHandler(fh)
            
        msg = f"{symbol},{action},{price:.2f},{qty},{profit:.2f},{volatility:.4f},{range_low},{range_high},{step:.2f},{step_pct:.2f}"
        logger.info(msg)
        
        for handler in logger.handlers:
            handler.flush()
    except Exception as e:
        print(f"Error logging tuning metrics: {e}")

def get_audit_logs():
    """Retrieve user audit logs."""
    return list(audit_logs)
