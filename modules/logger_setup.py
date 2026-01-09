import logging
import os
from . import config

def setup_logger():
    """Sets up the main logger and the trade-specific logger."""
    
    # 1. Clear log files on startup
    if os.path.exists(config.TRADING_LOG_FILE):
        open(config.TRADING_LOG_FILE, 'w').close()
    if os.path.exists(config.TRADE_LOG_FILE):
        open(config.TRADE_LOG_FILE, 'w').close()

    # 2. Main Logger Setup
    logger = logging.getLogger("BinanceTradingBot")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fh = logging.FileHandler(config.TRADING_LOG_FILE)  # Main log file
    fh.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)

    # 3. Trade Logger Setup
    trade_logger = logging.getLogger("trade_logger")
    trade_logger.setLevel(logging.INFO)
    trade_logger.propagate = False  # Prevent bubbling up to root

    # Ensure no duplicate handlers if called multiple times (though mainly for cleanup)
    if not trade_logger.handlers:
        trade_fh = logging.FileHandler(config.TRADE_LOG_FILE)
        trade_fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
        trade_logger.addHandler(trade_fh)

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
