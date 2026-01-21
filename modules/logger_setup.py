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
            
            # Persist to file
            try:
                with open(config.ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(log_entry + "\n")
            except Exception:
                pass
        except Exception:
            self.handleError(record)

def clear_errors():
    """Clears the recent error buffer and file."""
    recent_errors.clear()
    if os.path.exists(config.ERROR_LOG_FILE):
        with open(config.ERROR_LOG_FILE, 'w') as f:
            f.truncate(0)

def log_strategy(message, persist=True):
    """Logs a strategy update message."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{timestamp} - {message}"
    
    # 1. Update In-Memory Deque (for UI)
    strategy_logs.appendleft(entry)
    
    # 2. Persist to file (Append Mode)
    if persist:
        try:
            with open(config.STRATEGY_HISTORY_FILE, 'a', encoding='utf-8') as f:
                f.write(entry + "\n")
        except Exception:
            pass # Non-critical if logging fails

def load_strategy_history():
    """Restores last 50 logs from history file on startup."""
    try:
        if os.path.exists(config.STRATEGY_HISTORY_FILE):
             with open(config.STRATEGY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                 lines = f.readlines()
                 # Take last 50 lines, reverse them (newest first for deque)
                 last_lines = lines[-50:]
                 for line in reversed(last_lines):
                     strategy_logs.append(line.strip())
    except Exception as e:
        print(f"Failed to load strategy history: {e}")

def load_error_history():
    """Restores last 100 errors from history file on startup."""
    try:
        if os.path.exists(config.ERROR_LOG_FILE):
             with open(config.ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
                 lines = f.readlines()
                 last_lines = lines[-100:]
                 for line in reversed(last_lines):
                     recent_errors.append(line.strip())
    except Exception as e:
        print(f"Failed to load error history: {e}")

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
    
    # Persist structured audit log
    try:
        import json
        with open(config.AUDIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def load_audit_history():
    """Restores last 100 audit logs from history file on startup."""
    try:
        import json
        if os.path.exists(config.AUDIT_LOG_FILE):
             with open(config.AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
                 lines = f.readlines()
                 last_lines = lines[-100:]
                 for line in reversed(last_lines):
                     try:
                         entry = json.loads(line.strip())
                         audit_logs.append(entry)
                     except:
                         pass
    except Exception as e:
        print(f"Failed to load audit history: {e}")

def clear_audit_logs():
    """Clears audit logs."""
    audit_logs.clear()
    if os.path.exists(config.AUDIT_LOG_FILE):
        with open(config.AUDIT_LOG_FILE, 'w') as f:
            f.truncate(0)


def clear_activity_logs():
    """Clears the system activity logs (Trades + Main Debug)."""
    # 1. Clear Trade Log (Displayed in UI System Activity)
    if os.path.exists(config.TRADE_LOG_FILE):
        with open(config.TRADE_LOG_FILE, 'w') as f:
            f.truncate(0)
    
    # 2. Clear Main Debug Log (optional, but good for full clear)
    if os.path.exists(config.TRADING_LOG_FILE):
        with open(config.TRADING_LOG_FILE, 'w') as f:
            f.truncate(0)

def clear_strategy_logs():
    """Clears only the strategy tuning logs."""
    strategy_logs.clear()
    
    # Clear persistence file
    if os.path.exists(config.STRATEGY_HISTORY_FILE):
        with open(config.STRATEGY_HISTORY_FILE, 'w') as f:
            f.truncate(0)
            
    # Also clear detailed tuning CSV? Maybe keep it for analysis?
    # User asked for "strategy" clear, usually implies the UI list.
    # We can clear the CSV too to be safe/clean.
    if os.path.exists(config.TUNING_LOG_FILE):
        with open(config.TUNING_LOG_FILE, 'w') as f:
             f.truncate(0)
             # Write header again
             logging.getLogger("tuning_logger").info("Timestamp,Symbol,Action,Price,Qty,Profit,Volatility,RangeLow,RangeHigh,Step,StepPct")


def clear_all_logs():
    """Clears both system and strategy logs from memory AND disk."""
    recent_errors.clear()
    
    clear_activity_logs()
    clear_strategy_logs()
    clear_audit_logs()
    
    # Clear errors file
    if os.path.exists(config.ERROR_LOG_FILE):
        with open(config.ERROR_LOG_FILE, 'w') as f:
            f.truncate(0)

def setup_logger(name="BinanceTradingBot", log_file=config.TRADING_LOG_FILE):
    """Sets up the main logger and the trade-specific logger."""
    
    # 1. Clear log files on startup - DISABLED per user request for persistence
    # if os.path.exists(config.TRADING_LOG_FILE):
    #     open(config.TRADING_LOG_FILE, 'w').close()
    # if os.path.exists(config.TRADE_LOG_FILE):
    #     open(config.TRADE_LOG_FILE, 'w').close()

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
            
    # 5. Load History
    load_strategy_history()
    load_audit_history()
    load_error_history()

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
        
        # Add visible console print since we muted debug logs
        print(f"💰 {action.upper()}: Price {price} | Qty {quantity} | Val {total_value} | PnL {profit if profit else '0'}%")
        
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


# ============================================
# TRADE JOURNAL - Structured Trade Logging
# ============================================
TRADE_JOURNAL_FILE = 'logs/trade_journal.json'
trade_journal = []  # In-memory cache

def log_trade_journal(entry):
    """
    Log a structured trade entry to the journal.
    Entry should be a dict with:
    - timestamp, symbol, action (BUY/SELL)
    - price, qty, total_value
    - entry_reason (for buys) or exit_reason (for sells)
    - indicators: {rsi, macd_hist, volatility, fear_greed, trend_ma}
    - pnl_percent, pnl_amount (for sells)
    - hold_duration_minutes (for sells)
    """
    import json
    import datetime
    
    # Add timestamp if not present
    if 'timestamp' not in entry:
        entry['timestamp'] = datetime.datetime.now().isoformat()
    
    # Add to in-memory cache
    trade_journal.insert(0, entry)  # Newest first
    if len(trade_journal) > 500:
        trade_journal.pop()  # Keep last 500

    # Persist to file
    try:
        # Read existing
        existing = []
        if os.path.exists(TRADE_JOURNAL_FILE):
            with open(TRADE_JOURNAL_FILE, 'r', encoding='utf-8') as f:
                try:
                    existing = json.load(f)
                except:
                    existing = []
        
        # Prepend new entry
        existing.insert(0, entry)
        
        # Keep last 500
        existing = existing[:500]
        
        # Write back
        with open(TRADE_JOURNAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"Error saving trade journal: {e}")

def get_trade_journal(limit=50):
    """Retrieve trade journal entries."""
    import json
    
    # If in-memory is empty, load from file
    if not trade_journal:
        try:
            if os.path.exists(TRADE_JOURNAL_FILE):
                with open(TRADE_JOURNAL_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    trade_journal.extend(loaded[:500])
        except:
            pass
    
    return trade_journal[:limit]


# ============================================
# PERFORMANCE METRICS - Sharpe Ratio & More
# ============================================
EQUITY_HISTORY_FILE = 'logs/equity_history.json'
equity_history = []  # List of {timestamp, balance, pnl_percent}

def log_equity_snapshot(balance, trade_pnl_percent=None):
    """
    Log a balance snapshot for equity curve and Sharpe calculation.
    Call after each trade or periodically.
    """
    import json
    import datetime
    
    entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'balance': balance,
        'pnl_percent': trade_pnl_percent
    }
    
    equity_history.append(entry)
    
    # Keep last 1000 snapshots
    if len(equity_history) > 1000:
        equity_history.pop(0)
    
    # Persist to file
    try:
        with open(EQUITY_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(equity_history[-1000:], f, indent=2)
    except Exception as e:
        print(f"Error saving equity history: {e}")

def load_equity_history():
    """Load equity history from file on startup."""
    import json
    global equity_history
    
    try:
        if os.path.exists(EQUITY_HISTORY_FILE):
            with open(EQUITY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                equity_history = json.load(f)
    except:
        equity_history = []

def get_equity_history(limit=100):
    """Get recent equity snapshots for charting."""
    if not equity_history:
        load_equity_history()
    return equity_history[-limit:]

def calculate_sharpe_ratio(risk_free_rate=0.02):
    """
    Calculate Sharpe Ratio from equity history.
    risk_free_rate is annual (e.g., 0.02 = 2%)
    Returns: sharpe_ratio (annualized), or None if insufficient data
    """
    import math
    
    if not equity_history:
        load_equity_history()
    
    # Need at least 2 data points
    if len(equity_history) < 2:
        return None
    
    # Extract returns (pnl_percent from trades)
    returns = [e['pnl_percent'] for e in equity_history if e.get('pnl_percent') is not None]
    
    if len(returns) < 2:
        return None
    
    # Calculate mean and std of returns
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_return = math.sqrt(variance)
    
    if std_return == 0:
        return None
    
    # Annualize (assume ~250 trading days, but for crypto ~365)
    # For per-trade Sharpe, we just use raw figures
    # Convert annual risk-free to per-trade (rough approximation)
    per_trade_rf = risk_free_rate / 365  # ~0.005% per day
    
    sharpe = (mean_return - per_trade_rf) / std_return
    
    return round(sharpe, 2)

def get_performance_summary():
    """
    Get comprehensive performance summary.
    Returns dict with: sharpe_ratio, total_trades, win_rate, avg_return, max_drawdown
    """
    if not equity_history:
        load_equity_history()
    
    summary = {
        'sharpe_ratio': calculate_sharpe_ratio(),
        'total_snapshots': len(equity_history),
        'avg_return': None,
        'max_drawdown': None
    }
    
    returns = [e['pnl_percent'] for e in equity_history if e.get('pnl_percent') is not None]
    
    if returns:
        summary['avg_return'] = round(sum(returns) / len(returns), 2)
    
    # Calculate max drawdown from balance history
    if equity_history:
        balances = [e['balance'] for e in equity_history if e.get('balance')]
        if balances:
            peak = balances[0]
            max_dd = 0
            for bal in balances:
                if bal > peak:
                    peak = bal
                dd = ((peak - bal) / peak) * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            summary['max_drawdown'] = round(max_dd, 2)
    
    return summary

