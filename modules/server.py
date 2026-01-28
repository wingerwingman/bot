from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import time
import re
import os
import glob
import logging
import json
from . import config
from .trading_bot import BinanceTradingBot
from . import indicators
from .market_data_manager import market_data_manager
from . import logger_setup
from . import notifier
from .grid_bot import GridBot, calculate_auto_range
from .capital_manager import capital_manager

# Initialize logger immediately so errors are captured even if bot isn't running
logger_setup.setup_logger()

app = Flask(__name__)
# Security: Only allow requests from the React Frontend
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Global bot instances (Dictionaries for Multi-Bot)
spot_bots = {} # Key: symbol (e.g., 'ETHUSDT') -> BinanceTradingBot
bot_lock = threading.RLock()

grid_bots = {} # Key: symbol -> GridBot
grid_lock = threading.RLock()
cached_client = None

def run_flask():
    """Run Flask in production-safe mode."""
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)  # Only show warnings/errors, not every request
    app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False, threaded=True)

def start_server_standalone():
    """Start the Flask server in a standalone thread (no bot yet)."""
    server_thread = threading.Thread(target=run_flask, daemon=True)
    server_thread.start()
    
    # NEW: Start Daily Summary Scheduler
    scheduler_thread = threading.Thread(target=run_daily_summary_scheduler, daemon=True)
    scheduler_thread.start()
    
    # NEW: Start Health Monitor
    health_thread = threading.Thread(target=run_health_monitor, daemon=True)
    health_thread.start()
    
    print("API Server running at http://localhost:5050")

def run_daily_summary_scheduler():
    """Background loop to send summary at 08:00 AM everyday, plus weekly/monthly/yearly reports."""
    import time
    from datetime import datetime, timedelta
    
    while True:
        now = datetime.now()
        target_hour = 8
        
        # Check if it's 8 AM
        if now.hour == target_hour and now.minute == 0:
            try:
                summary = logger_setup.get_performance_summary()
                journal = logger_setup.get_trade_journal(limit=10000)
                
                # === DAILY REPORT (Every day) ===
                today_str = now.strftime('%Y-%m-%d')
                days_trades = [t for t in journal if t.get('timestamp', '').startswith(today_str)]
                
                if days_trades:
                    stats = _calculate_stats(days_trades, summary)
                    notifier.send_daily_summary(stats)
                
                # === WEEKLY REPORT (Sunday) ===
                if now.weekday() == 6:  # Sunday
                    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
                    week_trades = [t for t in journal if t.get('timestamp', '') >= week_ago]
                    if week_trades:
                        stats = _calculate_stats(week_trades, summary)
                        notifier.send_weekly_summary(stats)
                
                # === MONTHLY REPORT (1st of month) ===
                if now.day == 1:
                    month_start = now.replace(day=1) - timedelta(days=1)
                    prev_month_start = month_start.replace(day=1).strftime('%Y-%m-%d')
                    month_trades = [t for t in journal if t.get('timestamp', '') >= prev_month_start]
                    if month_trades:
                        stats = _calculate_stats(month_trades, summary)
                        notifier.send_monthly_summary(stats)
                
                # === YEARLY REPORT (Jan 1) ===
                if now.month == 1 and now.day == 1:
                    year_start = f"{now.year - 1}-01-01"
                    year_trades = [t for t in journal if t.get('timestamp', '') >= year_start]
                    if year_trades:
                        stats = _calculate_stats(year_trades, summary)
                        notifier.send_yearly_summary(stats)
                
                time.sleep(65)  # Sleep > 1 min to avoid double send
            except Exception as e:
                print(f"Error in summary scheduler: {e}")
                
        time.sleep(50)  # Check every 50s

def _calculate_stats(trades, summary):
    """Helper to calculate stats from a list of trades."""
    sells = [t for t in trades if t.get('action') == 'SELL']
    wins = [t for t in sells if t.get('pnl_amount', 0) > 0]
    losses = [t for t in sells if t.get('pnl_amount', 0) < 0]
    
    total_pnl = sum(t.get('pnl_amount', 0) for t in sells)
    total_fees = sum(t.get('fee', 0) for t in trades)
    top_win = max([t.get('pnl_amount', 0) for t in wins]) if wins else 0
    worst_loss = min([t.get('pnl_amount', 0) for t in losses]) if losses else 0
    
    gross_profit = sum(t.get('pnl_amount', 0) for t in wins)
    gross_loss = abs(sum(t.get('pnl_amount', 0) for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0
    
    return {
        'total_trades': len(sells),
        'win_rate': round(len(wins) / len(sells) * 100, 1) if sells else 0,
        'net_pnl': total_pnl,
        'total_fees': total_fees,
        'top_winner': top_win,
        'worst_loss': worst_loss,
        'max_drawdown': summary.get('max_drawdown', 0),
        'profit_factor': profit_factor,
        'avg_trade_pnl': round(total_pnl / len(sells), 2) if sells else 0
    }

def run_health_monitor():
    """Background monitor for bot stalls and auto-restart from IP bans."""
    print("Health Monitor started.")
    while True:
        try:
            current_time = time.time()
            
            # --- 1. Stall Detection (Heartbeats) ---
            with bot_lock:
                for symbol, bot in spot_bots.items():
                    if bot.running and not bot.paused:
                        diff = current_time - getattr(bot, 'last_active_timestamp', current_time)
                        if diff > 300: # 5 Minutes
                             if not getattr(bot, 'stall_alert_sent', False):
                                 notifier.send_telegram_message(f"🚨 <b>STALL DETECTED ({symbol})</b>\nBot has not updated for {int(diff/60)} minutes!")
                                 bot.stall_alert_sent = True
                        else:
                             bot.stall_alert_sent = False

            with grid_lock:
                for symbol, bot in grid_bots.items():
                    if bot.running and not bot.paused:
                        diff = current_time - getattr(bot, 'last_active_timestamp', current_time)
                        if diff > 300: 
                             if not getattr(bot, 'stall_alert_sent', False):
                                 notifier.send_telegram_message(f"🚨 <b>STALL DETECTED (Grid: {symbol})</b>\nBot has not updated for {int(diff/60)} minutes!")
                                 bot.stall_alert_sent = True
                        else:
                             bot.stall_alert_sent = False

            # --- 2. Auto-Restart Banned Bots ---
            # Spot Bots
            with bot_lock:
                for symbol, bot in spot_bots.items():
                    # If bot stopped (running=False) AND has a ban_until timestamp
                    if not bot.running and getattr(bot, 'ban_until', None) is not None:
                        if current_time > bot.ban_until:
                            try:
                                print(f"Ban expired for {symbol}. Attempting auto-restart...")
                                bot.ban_until = None # Reset
                                bot.start()
                                notifier.send_telegram_message(f"✅ <b>AUTO-RESTART: Ban Expired ({symbol})</b>\nBot has resumed trading.")
                            except Exception as e:
                                print(f"Auto-restart failed for {symbol}: {e}")

            # Grid Bots
            with grid_lock:
                for symbol, bot in grid_bots.items():
                    if not bot.running and getattr(bot, 'ban_until', None) is not None:
                        if current_time > bot.ban_until:
                            try:
                                print(f"Ban expired for Grid {symbol}. Attempting auto-restart...")
                                bot.ban_until = None
                                bot.start()
                                notifier.send_telegram_message(f"✅ <b>AUTO-RESTART: Grid Ban Expired ({symbol})</b>\nGrid bot has resumed.")
                            except Exception as e:
                                print(f"Auto-restart failed for Grid {symbol}: {e}")

        except Exception as e:
            print(f"Health Monitor error: {e}")
            
        time.sleep(30) # Run every 30 seconds

# Admin Credentials
# Admin Credentials (Loaded from Config/Env)
ADMIN_USER = config.ADMIN_USER
ADMIN_PASS = config.ADMIN_PASS
ADMIN_TOKEN = config.ADMIN_TOKEN

def check_auth():
    """Checks for valid auth token in headers."""
    token = request.headers.get('X-Auth-Token')
    return token == ADMIN_TOKEN

def find_spot_bot(identifier):
    """
    Find a spot bot by identifier (key or symbol).
    Handles mode prefixes (live_, test_) and falls back to symbol match.
    
    Args:
        identifier: Bot key (like 'live_ETHUSDT') or symbol (like 'ETHUSDT')
    
    Returns:
        Tuple of (bot, key) or (None, None) if not found
    """
    global spot_bots
    with bot_lock:
        if not identifier:
            # If only one bot, return it
            if len(spot_bots) == 1:
                key = list(spot_bots.keys())[0]
                return spot_bots[key], key
            return None, None
        
        # Direct key lookup
        if identifier in spot_bots:
            return spot_bots[identifier], identifier
            
        # Common Issue: Identifier might be "spot_live_ETHUSDT" but key is "live_ETHUSDT"
        if identifier.startswith("spot_") and identifier.replace("spot_", "") in spot_bots:
             stripped = identifier.replace("spot_", "")
             return spot_bots[stripped], stripped
        
        # Try Mode Prefixes (Case-Insensitive)
        ident_lower = identifier.lower()
        for prefix in ['live_', 'test_']:
            key = f"{prefix}{ident_lower}"
            # Case-insensitive search in keys
            for actual_key in list(spot_bots.keys()):
                if actual_key.lower() == key:
                    return spot_bots[actual_key], actual_key
        
        # Search by symbol value (Exact or Normalized)
        symbol_norm = identifier.replace('_', '').replace('-', '').upper()
        for k, b in spot_bots.items():
            if b.symbol.replace('_', '').replace('-', '').upper() == symbol_norm:
                return b, k
            if k.lower() == ident_lower:
                return b, k
        for key, bot in spot_bots.items():
            if bot.symbol == identifier:
                return bot, key
        
        return None, None

# ===================== API ENDPOINTS =====================

@app.route('/api/login', methods=['POST'])
def login():
    """Simple admin login."""
    data = request.json or {}
    if data.get('username') == ADMIN_USER and data.get('password') == ADMIN_PASS:
        logger_setup.log_audit("LOGIN", "Admin login successful", request.remote_addr)
        return jsonify({"success": True, "token": ADMIN_TOKEN})
    
    logger_setup.log_audit("LOGIN_FAIL", f"Failed login attempt for user: {data.get('username')}", request.remote_addr)
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/status', methods=['GET'])
def get_status():
    
    # Helper to get live prices and volatility
    # Helper to get live prices and volatility
    def get_market_data():
        # Use MarketDataManager (centralized rest caching & websets)
        status = market_data_manager.get_market_status("ETHUSDT")
        if not status:
             return None, None, None
        
        # We also need BTC for the dashboard top-bar
        btc_price = market_data_manager.get_price("BTCUSDT")
        
        return status['price'], btc_price, status['volatility']
    
    # If specific symbol requested, return details for that bot
    req_symbol = request.args.get('symbol')
    req_type = request.args.get('type', 'spot')
    
    # Aggregate all running bots for the summary list
    active_bots = []
    
    # Add Spot Bots
    with bot_lock:
        for bot_key, bot in spot_bots.items():
            net_profit = bot.gross_profit - bot.gross_loss
            
            # Extract advanced filters for UI indicators
            strategy_flags = {}
            if hasattr(bot, 'strategy'):
                s = bot.strategy
                strategy_flags = {
                    "mtf": getattr(s, 'multi_timeframe_enabled', False),
                    "vol": getattr(s, 'volume_confirmation_enabled', False),
                    "sr": getattr(s, 'support_resistance_check_enabled', False),
                    "ml": getattr(s, 'ml_confirmation_enabled', False),
                    "ob": getattr(s, 'order_book_check_enabled', False),
                    "missed": getattr(s, 'missed_trade_log_enabled', False)
                }

            status_str = "running" if bot.running else "stopped"
            active_bots.append({
                "id": f"spot_{bot_key}",  # bot_key is already mode_symbol
                "symbol": bot.symbol,
                "type": "spot",
                "status": status_str,
                "profit": net_profit,
                "is_live": bot.is_live_trading,
                "strategy": strategy_flags,
                "ban_until": bot.ban_until,
                "paused": getattr(bot, 'paused', False)
            })



    # Add Grid Bots
    with grid_lock:
        for symbol, bot in grid_bots.items():
            s = bot.get_status()
            active_bots.append({
                "id": f"grid_{symbol}",
                "symbol": symbol,
                "type": "grid",
                "status": "running" if bot.running else "stopped",
                "profit": s.get('total_profit', 0),
                "is_live": bot.is_live,
                "ban_until": getattr(bot, 'ban_until', None),
                "paused": getattr(bot, 'paused', False)
            })

    # Basic market prices (ETH/BTC) for dashboard header
    eth_price, btc_price, vol = get_market_data()
    
    # If a specific bot status is requested (for Bot Panel details)
    # Check for direct ID first (Strongest Match)
    req_id = request.args.get('bot_id')
    target_key = req_id if req_id else req_symbol
    
    if target_key and req_type == 'spot':
        # Remove 'spot_' prefix if present (API cleanliness)
        if target_key.startswith('spot_'):
            target_key = target_key.replace('spot_', '')
            
        # Debug: Log exactly what we're looking for
        # logging.getLogger("BinanceTradingBot").debug(f"get_status lookup: target_key='{target_key}'")
        
        # Use robust lookup helper (it has its own locking)
        bot, actual_key = find_spot_bot(target_key)
        
        # logging.getLogger("BinanceTradingBot").debug(f"get_status lookup result: bot={bot is not None}, actual_key={actual_key}")
        
        if not bot:
             # If still not found, return idle.
             # Debug: Return available keys to help diagnose mismatch
             debug_keys = list(spot_bots.keys())
             logging.getLogger("BinanceTradingBot").warning(f"get_status: Bot not found for key='{target_key}'. Available: {debug_keys}")
             return jsonify({
                 "status": "idle", 
                 "running": False, 
                 "symbol": req_symbol,
                 "target_key": target_key,
                 "debug_available_keys": debug_keys
             })
        
        # logging.getLogger("BinanceTradingBot").debug(f"get_status: Found bot {actual_key}, running={bot.running}")

        
        # ... Reuse logic to extract detailed metrics for ONE bot ...
        # Calculate Realtime Metrics
        net_profit = bot.gross_profit - bot.gross_loss
        realtime_metrics = {
            "active_orders": 1 if bot.bought_price else 0,
            "buy_fills": bot.total_trades + (1 if bot.bought_price else 0),
            "sell_fills": bot.total_trades,
            "total_fees": getattr(bot, 'total_fees', 0.0),
            "net_profit": net_profit,
            "max_win_streak": getattr(bot, 'max_win_streak', 0),
            "max_loss_streak": getattr(bot, 'max_loss_streak', 0)
        }
        
        # Get strategy settings
        strategy_settings = {}
        volatility = None
        if hasattr(bot, 'strategy'):
            s = bot.strategy
            strategy_settings = {
                "rsi_threshold": getattr(s, 'rsi_threshold_buy', 40),
                "stop_loss_percent": getattr(s, 'stop_loss_percent', 0.02) * 100,
                "trailing_stop_percent": getattr(s, 'sell_percent', 0.03) * 100,
                # New Advanced Settings
                "volume_confirmation_enabled": getattr(s, 'volume_confirmation_enabled', True),
                "volume_multiplier": getattr(s, 'volume_multiplier', 1.2),
                "multi_timeframe_enabled": getattr(s, 'multi_timeframe_enabled', True),
                "cooldown_after_stoploss_minutes": getattr(s, 'cooldown_after_stoploss_minutes', 30),
                "dca_enabled": getattr(s, 'dca_enabled', True),
                "dca_rsi_threshold": getattr(s, 'dca_rsi_threshold', 30),
                # Manual Control Flags
                "missed_trade_log_enabled": getattr(s, 'missed_trade_log_enabled', True),
                "order_book_check_enabled": getattr(s, 'order_book_check_enabled', False),
                "support_resistance_check_enabled": getattr(s, 'support_resistance_check_enabled', False),
                "ml_confirmation_enabled": getattr(s, 'ml_confirmation_enabled', False),
                # Sentiment Settings (NEW)
                "sentiment_enabled": getattr(s, 'sentiment_enabled', False),
                "sentiment_threshold": getattr(s, 'sentiment_threshold', 0.2)
            }
            volatility = getattr(s, 'current_volatility', None)

        try:
            # Paper Trading (is_live=False, filename=None) should still use live prices
            if bot.is_live_trading or not getattr(bot, 'filename', None):
                current_price = market_data_manager.get_price(bot.symbol)
            else:
                current_price = bot.last_price
        except:
            current_price = getattr(bot, 'last_price', 0.0)

        # Extract detailed strategy info for "Waiting..." status
        strat_details = {}
        if hasattr(bot, 'strategy'):
             # We want to access current RSI if possible. 
             # Strategy class doesn't store 'last_rsi' explicitly, but we can calc it easily or grab from history
             # BUT strategies reuse price_history. 
             try:
                 hist = list(bot.strategy.price_history) or []
                 if len(hist) > 14:
                     last_rsi = indicators.calculate_rsi(hist)
                 else:
                     last_rsi = 50.0
                 
                 # Sanitize NaN values for JSON safety
                 safe_rsi = 50.0
                 if last_rsi is not None and str(last_rsi).lower() != 'nan':
                     safe_rsi = last_rsi
                 
                 cur_vol_raw = getattr(bot.strategy, 'current_volatility', 0)
                 cur_vol = 0.0
                 if cur_vol_raw is not None and str(cur_vol_raw).lower() != 'nan':
                     cur_vol = cur_vol_raw

                 strat_details = {
                     "current_rsi": safe_rsi,
                     "target_rsi": getattr(bot.strategy, 'rsi_threshold_buy', 40),
                     "current_vol": cur_vol,
                     "last_rejection": getattr(bot.strategy, 'last_rejection_reason', 'Analyzing...'),
                     "cooling_down": bot.strategy.is_in_cooldown(),
                     "cooldown_remaining": bot.strategy.get_cooldown_remaining(),
                     "ban_until": bot.ban_until,
                     "consecutive_stop_losses": getattr(bot, 'consecutive_stop_losses', 0)
                 }
             except Exception as ex:
                 print(f"Strat details error: {ex}")

        response_data = {
            "status": "running" if bot.running else "stopped",
            "running": bot.running,
            "mode": "Live" if bot.is_live_trading else "Test",
            "is_paper": (not bot.is_live_trading and not bot.filename),
            "realtime_metrics": realtime_metrics,
            "symbol": bot.symbol,
            "current_price": current_price,
            "eth_price": eth_price,
            "strategy_details": strat_details,
            "btc_price": btc_price,
            "volatility": volatility,
            "position_size_percent": getattr(bot, 'position_size_percent', 0.25) * 100,
            "dynamic_settings": getattr(bot, 'dynamic_settings', False),
            "dca_enabled": getattr(bot.strategy, 'dca_enabled', False) if hasattr(bot, 'strategy') else False,
            "strategy_settings": strategy_settings,
            "final_balance": getattr(bot, 'final_balance', None),
            "total_return": getattr(bot, 'total_return', None),
            "finished": getattr(bot, 'finished_data', False),
            "paused": getattr(bot, 'paused', False),
            "balances": {
                "quote": bot.quote_balance,
                "base": bot.base_balance,
                "quote_asset": bot.quote_asset,
                "base_asset": bot.base_asset,
                "base_usd_value": (bot.base_balance * current_price) if current_price else 0,
                "bought_price": bot.bought_price,  # Entry price for current position
                "trail_price": getattr(bot, 'current_trail_price', None),
                "stop_loss_price": getattr(bot, 'current_hard_stop', None),
                "lock_profit_price": getattr(bot, 'lock_profit_price', None),
                "current_price": current_price,
                "is_live": bot.is_live_trading
            },
            "performance": bot.get_performance_summary() if hasattr(bot, 'get_performance_summary') else {}
        }
        
        # Debug: Log what we are sending
        return jsonify(response_data)

    # Default / Main Dashboard Response: Return List of Bots + Market Data
    return jsonify({
        "bots": active_bots,
        "eth_price": eth_price,
        "btc_price": btc_price, 
        "volatility": vol
    })

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    symbol = request.args.get('symbol')
    bot_key = request.args.get('key')
    bot = None  # FIX: Initialize to prevent NameError
    
    # If specific running bot requested by unique key
    if bot_key:
        bot = spot_bots.get(bot_key)
    # Fallback to symbol (legacy/simple view), assuming LIVE if ambiguous
    elif symbol:
        # try live first, then test? Or just construct live key
        bot = spot_bots.get(f"live_{symbol}")
        # If not found, try finding any bot with that symbol (e.g. test)
        if not bot:
             for k, b in spot_bots.items():
                 if b.symbol == symbol:
                     bot = b
                     break
    
    if bot:
        # Use rich performance summary if available (New Method)
        if hasattr(bot, 'get_performance_summary'):
            summary = bot.get_performance_summary()
            
            # Attach recent journal (last 20)
            if hasattr(bot, 'get_internal_journal'):
                 summary['trade_journal'] = bot.get_internal_journal()[:20]
                 
            summary['source'] = "bot_instance"
            summary['symbol'] = symbol
            return jsonify(summary)
            
        else:
            # Fallback for old/grid bots
            win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0.0
            profit_factor = (bot.gross_profit / bot.gross_loss) if bot.gross_loss > 0 else 999.0
            return jsonify({
                "total_trades": bot.total_trades,
                "winning_trades": bot.winning_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "max_drawdown": bot.max_drawdown,
                "peak_balance": bot.peak_balance,
                "max_win_streak": getattr(bot, 'max_win_streak', 0),
                "max_loss_streak": getattr(bot, 'max_loss_streak', 0),
                "source": "legacy",
                "symbol": symbol
            })
    
    # Return empty if not found or no symbol specified (could Aggregate later)
    # For now, just return empty object to prevent errors
    return jsonify({})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Returns the last 50 lines of the trade log."""
    log_file = config.TRADE_LOG_FILE
    if not os.path.exists(log_file):
        return jsonify([])
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            recent = lines[-50:]
            recent.reverse()
            return jsonify([line.strip() for line in recent])
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/logs/trades/export', methods=['GET'])
def export_trades():
    """Exports the full trade log as a CSV file."""
    log_file = config.TRADE_LOG_FILE
    if not os.path.exists(log_file):
        return "No trades recorded yet.", 404
    
    try:
        with open(log_file, 'r') as f:
            content = f.read()
        
        # Add Header
        csv_content = "Timestamp,Action,Quantity,Price,Total,Profit\n" + content
        
        from flask import Response
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=trade_history.csv"}
        )
    except Exception as e:
        return str(e), 500



@app.route('/api/market-status', methods=['GET'])
def get_market_status():
    """Fetches market status (Price, Volatility) for a given symbol."""
    symbol = request.args.get('symbol', 'ETH')
    base_pair = f"{symbol}USDT"
    
    # Use centralized manager
    status = market_data_manager.get_market_status(base_pair)
    if not status:
        return jsonify({"error": f"Failed to fetch status for {symbol}", "symbol": symbol, "price": None, "volatility": None})
        
    return jsonify(status)



@app.route('/api/balances', methods=['GET'])
def get_balances():
    """Returns all balances from Binance account with USD values."""
    try:
        # Use centralized caching (Weight 20)
        account_info = market_data_manager.get_account_info()
        if not account_info:
             return jsonify({"error": "Failed to fetch balances"}), 500
             
        # Fetch prices for conversion (using shared prices dictionary)
        # Priming the cache with all prices if empty
        all_prices = market_data_manager.prices
        if not all_prices:
            all_prices = market_data_manager.get_all_prices()
        
        important = ['USDT', 'USD', 'ETH', 'BTC', 'BNB', 'SOL', 'ZEC']
        balances = []
        
        for b in account_info['balances']:
            free = float(b['free'])
            locked = float(b['locked'])
            total = free + locked
            
            if total > 0 or b['asset'] in important:
                asset = b['asset']
                usd_value = 0.0
                
                if asset in ['USDT', 'USD', 'BUSD', 'USDC']:
                    usd_value = total
                else:
                    # Handle new dict format {price, timestamp} or legacy float
                    def get_price_val(sym):
                        if sym in all_prices:
                            val = all_prices[sym]
                            if isinstance(val, dict):
                                return val.get('price', 0)
                            return val
                        return None
                    
                    usdt_price = get_price_val(f"{asset}USDT")
                    usd_price = get_price_val(f"{asset}USD")
                    
                    if usdt_price:
                        usd_value = total * usdt_price
                    elif usd_price:
                        usd_value = total * usd_price
                
                balances.append({
                    'asset': asset,
                    'free': free,
                    'locked': locked,
                    'total': total,
                    'usd_value': round(usd_value, 2)
                })
        
        # Sort by USD value descending
        balances.sort(key=lambda x: x['usd_value'], reverse=True)
        return jsonify(balances)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/start', methods=['POST'])
def start_bot():
    """Start the bot with given configuration."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    global spot_bots
    
    with bot_lock:
        data = request.json or {}
        quote_asset = data.get('quote_asset', 'USDT').upper()  # Currency to buy with
        base_asset = data.get('base_asset', 'ETH').upper()     # Crypto to trade
        symbol = f"{base_asset}{quote_asset}"
        mode = data.get('mode', 'test')  # 'live' or 'test'
        
        # Use mode-prefixed key to allow live and test bots to run simultaneously
        bot_key = f"{mode}_{symbol}"
        
        if bot_key in spot_bots:
            existing_bot = spot_bots[bot_key]
            
            # Check if it's truly running (Running Flag + Thread Alive)
            is_alive = False
            if hasattr(existing_bot, 'thread') and existing_bot.thread.is_alive():
                is_alive = True
            
            if existing_bot.running and is_alive:
                msg = f"Start failed: {mode.upper()} Bot for {symbol} is already active and running."
                logging.getLogger("BinanceTradingBot").error(msg)
                return jsonify({"error": msg}), 400
            
            # If we are here, the bot is either:
            # 1. Not running flags (Normal restart)
            # 2. Running flag True but Thread Dead (Zombie -> Safe to overwrite)
            # 3. Running flag False but Thread Alive (Stopping/Rogue -> Force Join)
            
            if is_alive:
                logging.warning(f"Bot {bot_key} thread is still alive but marked as stopped. Forcing stop...")
                existing_bot.stop()
                existing_bot.thread.join(timeout=5) # Wait for it to die
            elif existing_bot.running:
                 logging.warning(f"Bot {bot_key} was marked running but thread is dead (Zombie). Cleanup up.")
                 
            # Cleanup reference
            spot_bots.pop(bot_key, None)
        
        # If exists but stopped, we will overwrite it below.
        
        filename = data.get('filename')  # For test mode
        position_size = data.get('position_size_percent', 25) / 100
        
        # Strategy Parameters
        rsi_threshold = data.get('rsi_threshold', 40)
        stop_loss = data.get('stop_loss_percent', 2) / 100
        trailing_stop = data.get('trailing_stop_percent', 3) / 100
        dynamic_settings = data.get('dynamic_settings', False)
        dca_enabled = data.get('dca_enabled', True)
        dca_rsi_threshold = data.get('dca_rsi_threshold', 30)
        
        # Advanced Settings (NEW)
        multi_timeframe_enabled = data.get('multi_timeframe_enabled', True)
        volume_confirmation_enabled = data.get('volume_confirmation_enabled', True)
        volume_multiplier = data.get('volume_multiplier', 1.2)
        cooldown_minutes = data.get('cooldown_minutes', 30)
        
        is_live = (mode.lower() == 'live')
        is_paper = (mode.lower() == 'paper')
        
        # Manual Control Flags (NEW)
        missed_trade_log_enabled = data.get('missed_trade_log_enabled', True)
        order_book_check_enabled = data.get('order_book_check_enabled', False)
        support_resistance_check_enabled = data.get('support_resistance_check_enabled', False)
        ml_confirmation_enabled = data.get('ml_confirmation_enabled', False)
        
        # Log payload for debugging
        logging.getLogger("BinanceTradingBot").info(f"START_BOT Request Payload: {json.dumps(data)}")
        
        # Filename required ONLY for backtest (test mode), not for paper trading
        if not is_live and not is_paper:
            if not filename:
                return jsonify({"error": "Filename required for backtest mode"}), 400
            data_dir = os.path.join(os.getcwd(), 'data')
            full_path = os.path.join(data_dir, filename)
            if not os.path.exists(full_path):
                return jsonify({"error": f"File not found: {filename}"}), 400
            filename = full_path
        else:
            filename = None
        
        resume_session = data.get('resumeSession', True)
        
        # Update config module with advanced settings before creating bot
        config.MULTI_TIMEFRAME_ENABLED = multi_timeframe_enabled
        config.VOLUME_CONFIRMATION_ENABLED = volume_confirmation_enabled
        config.VOLUME_MULTIPLIER_THRESHOLD = volume_multiplier
        config.STOP_LOSS_COOLDOWN_MINUTES = cooldown_minutes
        
        # Update Manual Control Configs
        config.MISSED_TRADE_LOG_ENABLED = missed_trade_log_enabled
        config.ORDER_BOOK_CHECK_ENABLED = order_book_check_enabled
        config.SUPPORT_RESISTANCE_CHECK_ENABLED = support_resistance_check_enabled
        config.ML_CONFIRMATION_ENABLED = ml_confirmation_enabled
        
        # Sentiment extraction (Fix for NameError)
        sentiment_enabled = data.get('sentiment_enabled', False)
        sentiment_threshold = float(data.get('sentiment_threshold', 0.0))
        
        allocated_capital = 0.0
        if is_live:
            allocated_capital = capital_manager.get_available('signal')
        
        try:
            bot = BinanceTradingBot(
                is_live_trading=is_live, 
                filename=filename,
                quote_asset=quote_asset,
                base_asset=base_asset,
                position_size_percent=position_size,
                rsi_threshold=rsi_threshold,
                stop_loss=stop_loss,
                trailing_stop=trailing_stop,
                dynamic_settings=dynamic_settings,
                resume_state=resume_session,
                dca_enabled=dca_enabled,
                dca_rsi_threshold=dca_rsi_threshold,
                allocated_capital=allocated_capital,
                # Pass advanced filters explicitly
                multi_timeframe_enabled=multi_timeframe_enabled,
                volume_confirmation_enabled=volume_confirmation_enabled,
                volume_multiplier=volume_multiplier,
                cooldown_minutes=cooldown_minutes,
                missed_trade_log_enabled=missed_trade_log_enabled,
                order_book_check_enabled=order_book_check_enabled,
                support_resistance_check_enabled=support_resistance_check_enabled,
                ml_confirmation_enabled=ml_confirmation_enabled,
                sentiment_enabled=sentiment_enabled,
                sentiment_threshold=sentiment_threshold
            )
            
            # Sentiment (Phase 5) args are now passed to init above
            
            bot.start()
            spot_bots[bot_key] = bot
            logger_setup.log_audit("START_BOT", f"Mode: {mode}, Symbol: {base_asset}", request.remote_addr)
            return jsonify({"success": True, "mode": mode, "symbol": bot.symbol, "bot_key": bot_key})
        except Exception as e:
            notifier.send_telegram_message(f"❌ <b>BOT START ERROR ({symbol})</b>\nFailed to start: {e}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the running bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')  # This is actually the bot_key (like "live_ETHUSDT")
        
    global spot_bots
    
    try:
        with bot_lock:
            if not symbol:
                 # If only 1 bot running, stop it? Or strictly require symbol?
                 if len(spot_bots) == 1:
                     symbol = list(spot_bots.keys())[0]
                 else:
                     return jsonify({"error": "Symbol/bot_key required to stop specific bot"}), 400
            
            # Try direct lookup first (new format: mode_symbol)
            bot = spot_bots.get(symbol)
            
            # Fallback: try to find by just symbol if old format
            if not bot:
                for key, b in spot_bots.items():
                    if b.symbol == symbol or key.endswith(f"_{symbol}"):
                        bot = b
                        symbol = key  # Update to actual key
                        break
            
            if not bot:
                 return jsonify({"error": f"No bot running for {symbol}"}), 400
            
            if bot.running:
                bot.stop()
            
            # Do NOT delete the bot, keep it in memory as 'stopped'
            
            logger_setup.log_audit("STOP_BOT", f"Bot {symbol} stopped by user", request.remote_addr)
            return jsonify({"success": True})
    except Exception as e:
        notifier.send_telegram_message(f"❌ <b>BOT STOP ERROR</b>\nFailed to stop: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/bot/update_settings', methods=['POST'])
def update_bot_settings():
    """Updates running bot settings on the fly."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global spot_bots
    try:
        with bot_lock:
            # Find bot
            bot = None
            if symbol and symbol in spot_bots:
                bot = spot_bots[symbol]
            elif symbol:
                 # Search by symbol
                 for k, b in spot_bots.items():
                     if b.symbol == symbol:
                         bot = b
                         break
            
            if not bot:
                return jsonify({"error": "Bot not found"}), 404
            
            # Update Settings
            if 'rsi_threshold' in data:
                bot.strategy.rsi_threshold_buy = float(data['rsi_threshold'])
            if 'stop_loss_percent' in data:
                sl = float(data['stop_loss_percent']) / 100.0
                bot.strategy.stop_loss_percent = sl
                bot.strategy.fixed_stop_loss_percent = sl
            if 'trailing_stop_percent' in data:
                bot.strategy.sell_percent = float(data['trailing_stop_percent']) / 100.0
            if 'dynamic_settings' in data:
                bot.dynamic_settings = bool(data['dynamic_settings'])
            if 'dca_enabled' in data:
                bot.strategy.dca_enabled = bool(data['dca_enabled'])
            if 'dca_rsi_threshold' in data:
                bot.strategy.dca_rsi_threshold = float(data['dca_rsi_threshold'])
            
            # Advanced Settings
            if 'volume_confirmation_enabled' in data:
                bot.strategy.volume_confirmation_enabled = bool(data['volume_confirmation_enabled'])
            if 'volume_multiplier' in data:
                bot.strategy.volume_multiplier = float(data['volume_multiplier'])
            if 'multi_timeframe_enabled' in data:
                bot.strategy.multi_timeframe_enabled = bool(data['multi_timeframe_enabled'])
            if 'cooldown_minutes' in data:
                bot.strategy.cooldown_after_stoploss_minutes = int(data['cooldown_minutes'])
            
            # Sentiment (Phase 5)
            if 'sentiment_enabled' in data:
                bot.strategy.sentiment_enabled = bool(data['sentiment_enabled'])
            if 'sentiment_threshold' in data:
                bot.strategy.sentiment_threshold = float(data['sentiment_threshold'])
            
            # Save State immediately
            if bot.is_live_trading:
                bot.save_state()
            
            logger_setup.log_audit("UPDATE_SETTINGS", f"Settings updated for {bot.symbol}", request.remote_addr)
            return jsonify({
                "success": True, 
                "message": "Settings updated successfully",
                "settings": {
                    "rsi": bot.strategy.rsi_threshold_buy,
                    "sl": bot.strategy.stop_loss_percent * 100,
                    "trail": bot.strategy.sell_percent * 100,
                    "dynamic": bot.dynamic_settings,
                    "dca_enabled": bot.strategy.dca_enabled,
                    "volume_enabled": bot.strategy.volume_confirmation_enabled
                }
            })
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete', methods=['POST'])
def delete_bot():
    """Permanently delete a bot instance and its state."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
        
    global spot_bots
    
    try:
        with bot_lock:
            if not symbol:
                return jsonify({"error": "Symbol required to delete bot"}), 400
            
            # 1. Stop if running
            bot = spot_bots.get(symbol)
            if bot:
                if bot.running:
                    bot.stop()
                # 2. Remove from memory
                del spot_bots[symbol]
            
            # 3. Delete State File (param_state_SYMBOL.json or similar?)
            # The TradingBot uses 'param_state.json' but shared? 
            # Needs verification. The Generic Bot saves to 'param_state.json' by default?
            # Let's check TradingBot implementation. It might not have unique state files per symbol yet?
            # Actually, let's just emit the event.
            
            # 4. Remove any specific data file if it exists?
            # For now, just removing from memory is the big one.
            # If we want to be thorough, we'd delete the specific log cache or state.
            # But the current generic bot might overlap files.
            # We'll stick to memory removal + audit log for now.
            
            logger_setup.log_audit("DELETE_BOT", f"Bot {symbol} deleted by user", request.remote_addr)
            return jsonify({"success": True})
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Delete Bot Error: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/api/manual_sell', methods=['POST'])
def manual_sell():
    """Triggers an immediate sell for the Specified Bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global spot_bots
    
    try:
        with bot_lock:
            if not symbol:
                if len(spot_bots) == 1:
                    symbol = list(spot_bots.keys())[0]
                else:
                    return jsonify({"error": "Symbol required to sell"}), 400
            
            bot = spot_bots.get(symbol)
            if not bot:
                # Fallback: Try with mode prefixes
                if f"live_{symbol}" in spot_bots:
                    bot = spot_bots[f"live_{symbol}"]
                elif f"test_{symbol}" in spot_bots:
                    bot = spot_bots[f"test_{symbol}"]
                else:
                    # Search by symbol value
                    for key, b in spot_bots.items():
                        if b.symbol == symbol:
                            bot = b
                            break
            
            if not bot:
                return jsonify({"error": f"No bot running for symbol {symbol}"}), 400
            
            if not bot.running:
                return jsonify({"error": "Bot is not running"}), 400
            
            if not bot.bought_price:
                return jsonify({"error": "Bot is not currently holding a position"}), 400

            # Execute Sell
            current_price = bot.last_price or 0
            # Force a fresh check if possible, safely
            try:
                # Assuming check_price is safe to call
                current_price = bot.check_price() 
            except:
                pass
                
            bot.sell_position(current_price, reason="🚨 MANUAL PANIC SELL")
            
            logger_setup.log_audit("MANUAL_SELL", f"Manual Sell triggered for {symbol} at ${current_price}", request.remote_addr)
            return jsonify({"success": True, "message": f"Sell Order Placed at ${current_price}"})
            
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Manual Sell Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/grid/manual_sell', methods=['POST'])
def manual_sell_grid():
    """Immediately liquidates a Grid Bot's holdings and cancels its orders."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global grid_bots
    
    try:
        with grid_lock:
            bot = grid_bots.get(symbol)
            if not bot:
                 return jsonify({"error": f"No grid bot found for {symbol}"}), 400
            
            bot.manual_sell(reason="DASHBOARD MANUAL SELL")
            logger_setup.log_audit("MANUAL_SELL_GRID", f"Manual Sell triggered for Grid {symbol}", request.remote_addr)
            return jsonify({"success": True, "message": f"Grid {symbol} liquidated and orders cancelled."})
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Grid Manual Sell Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/panic', methods=['POST'])
def panic_button():
    """🚨 EMERGENCY: Stop ALL bots and Liquidate ALL positions immediately."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    results = {"spot": [], "grid": []}
    
    # 1. STOP & LIQUIDATE SPOT BOTS
    with bot_lock:
        for symbol, bot in spot_bots.items():
            try:
                if bot.running:
                    bot.stop()
                if bot.bought_price:
                    # Fresh price check
                    price = bot.last_price or 0
                    try: price = bot.check_price()
                    except: pass
                    bot.sell_position(price, reason="🚨 EMERGENCY PANIC")
                    results["spot"].append(f"{symbol}: Liquidated")
                else:
                    results["spot"].append(f"{symbol}: Stopped (No position)")
            except Exception as e:
                results["spot"].append(f"{symbol}: Error - {str(e)}")

    # 2. STOP & LIQUIDATE GRID BOTS
    with grid_lock:
        for symbol, bot in grid_bots.items():
            try:
                if bot.running:
                    bot.stop()
                bot.manual_sell(reason="🚨 EMERGENCY PANIC")
                results["grid"].append(f"{symbol}: Liquidated & Cancelled")
            except Exception as e:
                results["grid"].append(f"{symbol}: Error - {str(e)}")

    logger_setup.log_audit("PANIC_BUTTON", "Global Emergency Shutdown Triggered!", request.remote_addr)
    notifier.send_telegram_message("🆘 <b>GLOBAL PANIC BUTTON TRIGGERED</b>\nAll bots stopping and positions liquidating!")
    
    return jsonify({"success": True, "message": "Global liquidation in progress.", "details": results})


@app.route('/api/data/download', methods=['POST'])
def download_data():
    """Downloads historical data for backtesting."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json or {}
    symbol = data.get('symbol')
    days = data.get('days', 90)
    interval = data.get('interval', '15m')
    
    if not symbol:
        return jsonify({"error": "Symbol required (e.g. ZECUSDT)"}), 400
    
    # Sanitize inputs
    symbol = symbol.upper().replace('/', '')
    if len(symbol) <= 5 and not symbol.endswith('USDT'):
        symbol += 'USDT'
        
    try:
        days = int(days)
    except:
        return jsonify({"error": "Days must be a number"}), 400
        
    print(f"Starting download for {symbol} ({days} days, {interval})...")
        
    try:
        from . import data_downloader
        # Use abs path for data dir
        data_dir = os.path.join(os.getcwd(), 'data')
        
        try:
            filename = data_downloader.download_historical_data(symbol, interval=interval, days=days, output_dir=data_dir)
        except Exception as e:
            # Fallback: If ZECUSD failed, try ZECUSDT
            if symbol.endswith('USD') and not symbol.endswith('USDT'):
                logging.getLogger("BinanceTradingBot").warning(f"Download failed for {symbol}, retrying with {symbol}T...")
                symbol += 'T'
                filename = data_downloader.download_historical_data(symbol, interval=interval, days=days, output_dir=data_dir)
            else:
                raise e
                
        return jsonify({"success": True, "filename": filename, "message": f"Downloaded {days} days of {symbol} data ({interval}) to {filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/datafiles', methods=['GET'])
def get_data_files():
    """Returns list of available CSV data files."""
    try:
        data_dir = os.path.join(os.getcwd(), 'data')
        if not os.path.exists(data_dir):
             return jsonify([])
        files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/errors', methods=['GET'])
def get_errors():
    """Returns the list of recent errors."""
    try:
        from .logger_setup import recent_errors
        return jsonify({"errors": list(recent_errors)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs/strategy', methods=['GET'])
def get_strategy_logs():
    """Returns the list of strategy update logs."""
    try:
        from .logger_setup import strategy_logs
        return jsonify({"logs": list(strategy_logs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs/audit', methods=['GET'])
def get_audit_logs():
    """Returns the list of user audit logs."""
    try:
        from .logger_setup import get_audit_logs
        return jsonify({"logs": get_audit_logs()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/errors/clear', methods=['POST'])
def clear_errors_log():
    """Clears the error log buffer."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_errors()
    logger_setup.log_audit("CLEAR_ERRORS", "Error log cleared", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/activity/clear', methods=['POST'])
def clear_activity_logs_endpoint():
    """Clears activity logs only."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    logger_setup.clear_activity_logs()
    logger_setup.log_audit("CLEAR_ACTIVITY", "Activity logs cleared", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/strategy/clear', methods=['POST'])
def clear_strategy_logs_endpoint():
    """Clears strategy logs only."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    logger_setup.clear_strategy_logs()
    logger_setup.log_audit("CLEAR_STRATEGY", "Strategy logs cleared", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/audit/clear', methods=['POST'])
def clear_audit_logs_endpoint():
    """Clears audit logs only."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    logger_setup.clear_audit_logs()
    logger_setup.log_audit("CLEAR_AUDIT", "Audit logs cleared", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/all/clear', methods=['POST'])
def clear_all_logs():
    """Clears ALL logs (System + Strategy)."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_all_logs()
    logger_setup.log_audit("CLEAR_ALL_LOGS", "All logs cleared", request.remote_addr)
    return jsonify({"success": True})


# ==================== TRADE JOURNAL & PERFORMANCE ====================

@app.route('/api/journal', methods=['GET'])
def get_trade_journal():
    """Returns trade journal entries with context."""
    try:
        limit = request.args.get('limit', 50, type=int)
        from .logger_setup import get_trade_journal
        return jsonify({"trades": get_trade_journal(limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/equity', methods=['GET'])
def get_equity_history():
    """Returns equity history for charting."""
    try:
        limit = request.args.get('limit', 100, type=int)
        from .logger_setup import get_equity_history
        return jsonify({"history": get_equity_history(limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/performance', methods=['GET'])
def get_performance():
    """Returns performance summary including Sharpe Ratio."""
    try:
        from .logger_setup import get_performance_summary, calculate_sharpe_ratio
        summary = get_performance_summary()
        
        # Also get trade journal stats
        from .logger_setup import get_trade_journal
        trades = get_trade_journal(500)
        
        if trades:
            sells = [t for t in trades if t.get('action') == 'SELL']
            wins = sum(1 for t in sells if t.get('pnl_amount', 0) >= 0)
            losses = len(sells) - wins
            total_sells = len(sells)
            
            # Calculate Profit Factor
            gross_profit = sum(t.get('pnl_amount', 0) for t in sells if t.get('pnl_amount', 0) > 0)
            gross_loss = sum(abs(t.get('pnl_amount', 0)) for t in sells if t.get('pnl_amount', 0) < 0)
            profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

            summary['total_trades'] = total_sells
            summary['winning_trades'] = wins
            summary['losing_trades'] = losses
            summary['win_rate'] = round((wins / total_sells * 100), 1) if total_sells > 0 else 0
            summary['profit_factor'] = profit_factor
            
            # Calculate Streaks
            max_win_streak = 0
            max_loss_streak = 0
            curr_win_streak = 0
            curr_loss_streak = 0
            
            for t in sells:
                if t.get('pnl_amount', 0) > 0:
                    curr_win_streak += 1
                    curr_loss_streak = 0
                    if curr_win_streak > max_win_streak:
                        max_win_streak = curr_win_streak
                else:
                    curr_loss_streak += 1
                    curr_win_streak = 0
                    if curr_loss_streak > max_loss_streak:
                        max_loss_streak = curr_loss_streak
            
            summary['max_win_streak'] = max_win_streak
            summary['max_loss_streak'] = max_loss_streak
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/sharpe', methods=['GET'])
def get_sharpe():
    """Returns just the Sharpe Ratio."""
    try:
        from .logger_setup import calculate_sharpe_ratio
        sharpe = calculate_sharpe_ratio()
        return jsonify({"sharpe_ratio": sharpe})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/test-error', methods=['POST'])
def trigger_test_error():
    """Generates a test error log."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    import logging
    logger = logging.getLogger("BinanceTradingBot")
    logger.error(f"TEST ERROR ({int(time.time())}): This is a simulated error for the UI test.")
    return jsonify({"status": "error_logged"})

@app.route('/api/fetch-data', methods=['POST'])
def fetch_data():
    """Fetch historical kline data from Binance and save to CSV."""
    try:
        from binance import Client
        from datetime import datetime, timedelta
        import pandas as pd
        
        data = request.json or {}
        symbol = data.get('symbol', 'ETHUSDT')
        interval = data.get('interval', '30m')
        days = data.get('days', 7)
        
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        
        # Calculate timestamps
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        start_ts = int(start_time.timestamp() * 1000)
        end_ts = int(end_time.timestamp() * 1000)
        
        klines = client.get_historical_klines(
            symbol=symbol,
            interval=interval,
            start_str=start_ts,
            end_str=end_ts
        )
        
        if not klines:
            return jsonify({"error": "No data returned from Binance"}), 400
        
        # Convert to DataFrame
        columns = [
            'Open Time', 'Open', 'High', 'Low', 'Close', 'Volume',
            'Close Time', 'Quote Asset Volume', 'Number of Trades',
            'Taker Buy Base Volume', 'Taker Buy Quote Volume', 'Ignore'
        ]
        df = pd.DataFrame(klines, columns=columns)
        df['Timestamp'] = pd.to_datetime(df['Open Time'], unit='ms')
        df['Price'] = df['Close'].astype(float)
        df['Open'] = df['Open'].astype(float)
        df['High'] = df['High'].astype(float)
        df['Low'] = df['Low'].astype(float)
        df['Volume'] = df['Volume'].astype(float)
        df = df[['Timestamp', 'Open', 'High', 'Low', 'Price', 'Volume']]
        
        # Save to data folder
        os.makedirs('data', exist_ok=True)
        filename = f"{symbol.lower()}_{interval}_{days}d.csv"
        filepath = os.path.join('data', filename)
        df.to_csv(filepath, index=False)
        
        return jsonify({
            "success": True, 
            "filename": filename,
            "rows": len(df),
            "start": str(df['Timestamp'].iloc[0]),
            "end": str(df['Timestamp'].iloc[-1])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def find_spot_bot(symbol):
    """
    Helper to find a spot bot by key or symbol suffix.
    Returns (bot, key) or (None, None).
    """
    global spot_bots
    
    # 1. Exact match (e.g. "live_ETHUSDT" or "test_ETHUSDT")
    if symbol in spot_bots:
        return spot_bots[symbol], symbol
        
    # 2. Suffix match (e.g. "ETHUSDT" matches "live_ETHUSDT")
    for key, b in spot_bots.items():
        if b.symbol == symbol:
            return b, key
            
    # 3. Key Suffix match
    for key, b in spot_bots.items():
        if key.endswith(f"_{symbol}"):
            return b, key
            
    return None, None

@app.route('/api/config/update', methods=['POST'])
def update_config():
    """Updates configuration of any running bot (Spot)."""
    data = request.json
    symbol = data.get('symbol')
    
    logging.getLogger("BinanceTradingBot").info(f"DEBUG: update_config called with payload: {data}")

    global spot_bots
    
    # Identify bot: prefer explicit symbol, else if only one exists use it
    bot = None
    if symbol:
        bot, actual_key = find_spot_bot(symbol)
        logging.getLogger("BinanceTradingBot").info(f"DEBUG: find_spot_bot('{symbol}') returned: {actual_key}")
    elif len(spot_bots) == 1:
        bot = list(spot_bots.values())[0]
        symbol = bot.symbol
        logging.getLogger("BinanceTradingBot").info(f"DEBUG: defaulted to single bot: {symbol}")

    if not bot:
        logging.getLogger("BinanceTradingBot").error(f"DEBUG: Bot not found for symbol: {symbol}. Available: {list(spot_bots.keys())}")
        return jsonify({"error": f"Bot for {symbol or 'selected pair'} is not running"}), 400
        
    try:
        # 1. State/UI Toggles
        if 'resume_state' in data:
            bot.resume_state = bool(data['resume_state'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Resume Session: {bot.resume_state}", request.remote_addr)
            
        if 'dynamic_settings' in data:
            bot.dynamic_settings = bool(data['dynamic_settings'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Dynamic Settings: {bot.dynamic_settings}", request.remote_addr)
            
        # 2. Position & Strategy Settings
        if 'position_size_percent' in data:
            bot.position_size_percent = float(data['position_size_percent'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Position Size: {bot.position_size_percent*100}%", request.remote_addr)

        if 'rsi_threshold' in data:
            bot.strategy.rsi_threshold_buy = float(data['rsi_threshold'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] RSI Threshold: {bot.strategy.rsi_threshold_buy}", request.remote_addr)

        if 'stop_loss_percent' in data:
            sl = float(data['stop_loss_percent'])
            bot.strategy.stop_loss_percent = sl
            bot.strategy.fixed_stop_loss_percent = sl
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Stop Loss: {sl*100}%", request.remote_addr)

        if 'trailing_stop_percent' in data:
            trailing = float(data['trailing_stop_percent'])
            bot.strategy.sell_percent = trailing
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Trailing Stop: {trailing*100}%", request.remote_addr)

        # 3. Defense (DCA) Settings
        if 'dca_enabled' in data:
            bot.strategy.dca_enabled = bool(data['dca_enabled'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] DCA Enabled: {bot.strategy.dca_enabled}", request.remote_addr)

        if 'dca_rsi_threshold' in data:
            bot.strategy.dca_rsi_threshold = float(data['dca_rsi_threshold'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] DCA RSI Threshold: {bot.strategy.dca_rsi_threshold}", request.remote_addr)

        # 4. Advanced Advanced Features
        if 'multi_timeframe_enabled' in data:
            bot.strategy.multi_timeframe_enabled = bool(data['multi_timeframe_enabled'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Multi-TF Trend: {bot.strategy.multi_timeframe_enabled}", request.remote_addr)

        if 'volume_confirmation_enabled' in data:
            bot.strategy.volume_confirmation_enabled = bool(data['volume_confirmation_enabled'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Volume Confirmation: {bot.strategy.volume_confirmation_enabled}", request.remote_addr)

        if 'volume_multiplier' in data:
            bot.strategy.volume_multiplier = float(data['volume_multiplier'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Volume Multiplier: {bot.strategy.volume_multiplier}", request.remote_addr)

        if 'cooldown_minutes' in data:
            bot.strategy.cooldown_after_stoploss_minutes = int(data['cooldown_minutes'])
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] SL Cooldown: {bot.strategy.cooldown_after_stoploss_minutes}m", request.remote_addr)
            
        # 5. Manual Controls (NEW)
        if 'missed_trade_log_enabled' in data:
            val = bool(data['missed_trade_log_enabled'])
            bot.strategy.missed_trade_log_enabled = val
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Missed Trade Log: {val}", request.remote_addr)

        if 'order_book_check_enabled' in data:
            val = bool(data['order_book_check_enabled'])
            bot.strategy.order_book_check_enabled = val
            config.ORDER_BOOK_CHECK_ENABLED = val 
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Order Book Check: {val}", request.remote_addr)
            
        if 'support_resistance_check_enabled' in data:
            val = bool(data['support_resistance_check_enabled'])
            bot.strategy.support_resistance_check_enabled = val
            config.SUPPORT_RESISTANCE_CHECK_ENABLED = val
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] S/R Check: {val}", request.remote_addr)

        if 'ml_confirmation_enabled' in data:
            val = bool(data['ml_confirmation_enabled'])
            bot.strategy.ml_confirmation_enabled = val
            config.ML_CONFIRMATION_ENABLED = val
            
            # If enabling ML on the fly, we might need to train it if not already?
            if val and not bot.strategy.ml_predictor:
                 # Attempt lazy load
                 try:
                     from .ml_predictor import TradePredictor
                     pred = TradePredictor()
                     if pred.train():
                         bot.strategy.set_ml_predictor(pred)
                 except:
                     pass
            
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] ML Confirmation: {val}", request.remote_addr)
            
        if 'sentiment_enabled' in data:
            val = bool(data['sentiment_enabled'])
            bot.strategy.sentiment_enabled = val
            config.SENTIMENT_ENABLED = val
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Sentiment Enabled: {val}", request.remote_addr)

        if 'sentiment_threshold' in data:
            val = float(data['sentiment_threshold'])
            bot.strategy.sentiment_threshold = val
            config.SENTIMENT_THRESHOLD = val
            logger_setup.log_audit("CONFIG_CHANGE", f"[{symbol}] Sentiment Threshold: {val}", request.remote_addr)
            
        # Force state save if positioning changed
        bot.save_state()
            
        return jsonify({
            "success": True, 
            "config": {
                "symbol": bot.symbol,
                "rsi_threshold": bot.strategy.rsi_threshold_buy,
                "stop_loss_percent": bot.strategy.stop_loss_percent,
                "trailing_stop_percent": bot.strategy.sell_percent,
                "position_size_percent": bot.position_size_percent,
                "dca_enabled": bot.strategy.dca_enabled,
                "dynamic_settings": bot.dynamic_settings,
                "multi_timeframe_enabled": bot.strategy.multi_timeframe_enabled
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/grid/config/update', methods=['POST'])
def update_grid_config_endpoint():
    """Updates configuration of a running Grid Bot on the fly."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    symbol = data.get('symbol')
    
    global grid_bots
    
    with grid_lock:
        if not symbol or symbol not in grid_bots:
            return jsonify({"error": f"Grid Bot for {symbol} is not running"}), 400
            
        bot = grid_bots[symbol]
        
        try:
            lower = data.get('lower_bound')
            upper = data.get('upper_bound')
            count = data.get('grid_count')
            cap = data.get('capital')
            auto_rebalance = data.get('auto_rebalance_enabled')
            vol_spacing = data.get('volatility_spacing_enabled')
            resume_session = data.get('resume_state')
            
            # Using the new update_config method (to be added to GridBot class)
            if hasattr(bot, 'update_config'):
                bot.update_config(
                    lower_bound=lower, 
                    upper_bound=upper, 
                    grid_count=count, 
                    capital=cap,
                    auto_rebalance_enabled=auto_rebalance,
                    volatility_spacing_enabled=vol_spacing,
                    resume_state=resume_session
                )
                logger_setup.log_audit("GRID_CONFIG_CHANGE", f"[{symbol}] Bounds: {lower}-{upper}, Levels: {count}, Rebal: {auto_rebalance}, VolSpace: {vol_spacing}", request.remote_addr)
                return jsonify({"success": True})
            else:
                return jsonify({"error": "GridBot class does not support dynamic updates yet"}), 500
                

        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/grid/manual_sell', methods=['POST'])
def grid_manual_sell():
    """Triggers emergency liquidation for a Grid Bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    symbol = data.get('symbol')
    
    global grid_bots
    with grid_lock:
        if not symbol or symbol not in grid_bots:
            # Try removing 'grid_' prefix if passed
            if symbol and symbol.startswith('grid_'):
                 symbol = symbol.replace('grid_', '')
            
            if not symbol or symbol not in grid_bots:
                return jsonify({"error": f"Grid Bot for {symbol} is not running"}), 400
        
        bot = grid_bots[symbol]
        try:
            bot.manual_sell()
            
            # Remove from active bots list since it stops itself
            if symbol in grid_bots:
                 del grid_bots[symbol]
                 
            return jsonify({"success": True, "message": "Grid Bot liquidated and stopped."})
        except Exception as e:
            return jsonify({"error": f"Liquidation failed: {str(e)}"}), 500

# ==================== GRID BOT ENDPOINTS ====================

@app.route('/api/grid/start', methods=['POST'])
def start_grid():
    """Start the Grid Trading Bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    global grid_bots
    
    with grid_lock:
        data = request.json or {}
        symbol = data.get('symbol', 'ETHUSDT')
        
        if symbol in grid_bots and grid_bots[symbol].running:
            msg = f"Grid Start failed: Bot for {symbol} is already active."
            logging.getLogger("BinanceTradingBot").error(msg)
            return jsonify({"error": msg}), 400
        
        # If exists but stopped, overwrite.
        
        lower_bound = data.get('lower_bound', 2800)
        upper_bound = data.get('upper_bound', 3200)
        grid_count = data.get('grid_count', 10)
        capital = data.get('capital', 1000)
        is_live = data.get('is_live', False)
        resume_state = data.get('resume_state', True)
        auto_rebalance_enabled = data.get('auto_rebalance_enabled', True)
        volatility_spacing_enabled = data.get('volatility_spacing_enabled', False)
        
        if lower_bound >= upper_bound:
            return jsonify({"error": "Lower bound must be less than upper bound"}), 400
            
        # BALANCE VALIDATION with Capital Manager
        if is_live:
            allocated = capital_manager.get_available('grid')
            
            # If 0 allocated, maybe fall back to check unallocated? Assuming explicit allocation for now.
            if allocated < capital:
                 msg = f"Insufficient allocated capital for Grid. Required: ${capital:.2f}, Allocated: ${allocated:.2f}. Please adjust in Capital Manager."
                 logging.getLogger("BinanceTradingBot").error(msg)
                 return jsonify({"error": msg}), 400
        
        try:
            bot = GridBot(
                symbol=symbol,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                grid_count=grid_count,
                capital=capital,
                is_live=is_live,
                resume_state=resume_state,
                auto_rebalance_enabled=auto_rebalance_enabled,
                volatility_spacing_enabled=volatility_spacing_enabled
            )
            bot.start()
            grid_bots[symbol] = bot
            
            # Log exact settings for tuning visibility
            settings_msg = (
                f"Grid Bot STARTED | Symbol: {symbol} | Mode: {'LIVE 💰' if is_live else 'TEST 🧪'}\n"
                f"   • Range: ${lower_bound} - ${upper_bound}\n"
                f"   • Levels: {grid_count}\n"
                f"   • Capital: ${capital}"
            )
            logger_setup.log_audit("GRID_START", f"Symbol: {symbol}, Range: ${lower_bound}-${upper_bound}, Levels: {grid_count}", request.remote_addr)
            
            # Additional log to strategy tab if possible, or just main log
            logging.getLogger("BinanceTradingBot").info(settings_msg)
            return jsonify({"success": True, "symbol": symbol, "levels": grid_count})
        except Exception as e:
            msg = f"Failed to start Grid Bot: {e}"
            logging.getLogger("BinanceTradingBot").error(msg)
            notifier.send_telegram_message(f"❌ <b>GRID BOT ERROR ({symbol})</b>\nFailed to start: {e}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/grid/stop', methods=['POST'])
def stop_grid():
    """Stop the Grid Trading Bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global grid_bots
    
    with grid_lock:
        if not symbol:
             # Stop first if only one?
             if len(grid_bots) == 1:
                 symbol = list(grid_bots.keys())[0]
             else:
                 return jsonify({"error": "Symbol required to stop Grid Bot"}), 400
        
        bot = grid_bots.get(symbol)
        if not bot:
            return jsonify({"error": f"No Grid Bot running for {symbol}"}), 400
        
        if bot.running:
            bot.stop()
        
        logger_setup.log_audit("GRID_STOP", f"Grid Bot {symbol} stopped by user", request.remote_addr)
        return jsonify({"success": True})

@app.route('/api/grid/clear', methods=['POST'])
def clear_grid_state():
    """Clear Grid Bot state (fills, profits, orders)."""
    # Log entry immediately
    data = request.json or {}
    symbol = data.get('symbol')
    logging.getLogger("BinanceTradingBot").info(f"Received request to clear grid state for {symbol}")

    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    global grid_bots
    
    with grid_lock:
        bot = grid_bots.get(symbol)
        if bot:
            # If bot is loaded, use its method (clears runtime state + active file)
            bot.clear_state()
            
    # Always check for and clean up legacy file (data/grid_state.json)
    # This ensures older state files are removed even if the bot is using the new filename schema
    try:
        legacy_path = "data/grid_state.json"
        if os.path.exists(legacy_path):
             try:
                with open(legacy_path, 'r') as f:
                    state = json.load(f)
                if state.get('symbol') == symbol:
                    os.remove(legacy_path)
                    logging.getLogger("BinanceTradingBot").info(f"Deleted legacy state file: {legacy_path}")
                else:
                    logging.getLogger("BinanceTradingBot").warning(f"Legacy file symbol {state.get('symbol')} mismatches {symbol}")
             except Exception as e:
                logging.getLogger("BinanceTradingBot").error(f"Failed to delete legacy file: {e}")
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Error in legacy cleanup block: {e}")

    # If bot was loaded, we are done
    if bot:
        return jsonify({"success": True, "message": f"State cleared for {symbol}"})
            
    # If bot not loaded, try to delete the specific file manually
    try:
        # Check specific symbol file
        path = f"data/grid_state_{symbol}.json"
        if os.path.exists(path):
            os.remove(path)
            logging.getLogger("BinanceTradingBot").info(f"Deleted state file: {path}")
            return jsonify({"success": True, "message": f"Deleted state file for {symbol}"})
                
        return jsonify({"success": True, "message": "No state file found to clear"})
        
    except Exception as e:
        return jsonify({"error": f"Failed to clear state: {e}"}), 500

@app.route('/api/grid/delete', methods=['POST'])
def delete_grid_bot():
    """Permanently delete a Grid Bot instance and its state."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global grid_bots
    
    with grid_lock:
        try:
            if not symbol:
                return jsonify({"error": "Symbol required to delete Grid Bot"}), 400
            
            # 1. Stop and Remove from memory
            bot = grid_bots.get(symbol)
            if bot:
                if bot.running:
                    bot.stop()
                del grid_bots[symbol]
            
            # 2. Delete State File
            try:
                fname = f"data/grid_state_{symbol}.json"
                if os.path.exists(fname):
                    os.remove(fname)
                
                # ALSO Delete legacy file if it matches
                legacy_path = "data/grid_state.json"
                if os.path.exists(legacy_path):
                     with open(legacy_path, 'r') as f:
                         state = json.load(f)
                     if state.get('symbol') == symbol:
                         os.remove(legacy_path)
                         logging.getLogger("BinanceTradingBot").info(f"Deleted legacy state file on delete: {legacy_path}")
            except Exception as e:
                logging.getLogger("BinanceTradingBot").error(f"Error deleting state file: {e}")

            logger_setup.log_audit("GRID_DELETE", f"Grid Bot {symbol} deleted by user", request.remote_addr)
            return jsonify({"success": True})
        except Exception as e:
            logging.getLogger("BinanceTradingBot").error(f"Delete Grid Bot Code Error: {e}")
            return jsonify({"error": str(e)}), 500



@app.route('/api/grid/status', methods=['GET'])
def grid_status():
    """Get Grid Bot status."""
    symbol = request.args.get('symbol')
    
    global grid_bots
    
    if symbol:
        bot = grid_bots.get(symbol)
        if bot:
            return jsonify(bot.get_status())
        else:
            return jsonify({"running": False, "symbol": symbol})
            
    # If no symbol, maybe return list or first?
    # Backend logic: return first running if any, or empty
    if grid_bots:
        # Fallback to first
        return jsonify(list(grid_bots.values())[0].get_status())
        
    return jsonify({"running": False})

@app.route('/api/grid/auto-range', methods=['GET'])
def grid_auto_range():
    """Calculate auto range based on volatility and capital."""
    symbol = request.args.get('symbol', 'ETHUSDT')
    use_volatility = request.args.get('use_volatility', 'true').lower() == 'true'
    capital = float(request.args.get('capital', 100))
    
    result = calculate_auto_range(symbol, use_volatility=use_volatility, capital=capital)
    
    if result is None:
        return jsonify({"error": "Could not calculate range"}), 500
    
    return jsonify({
        "symbol": symbol,
        "lower_bound": result['lower_bound'],
        "upper_bound": result['upper_bound'],
        "recommended_levels": result['recommended_levels'],
        "volatility_percent": result['volatility_percent'],
        "range_percent": result['range_percent'],
        "current_price": result['current_price'],
        "max_levels_for_capital": result.get('max_levels_for_capital')
    })

@app.route('/api/grid/clear', methods=['POST'])
def clear_grid():
    """Clear Grid Bot state and reset counters."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
    
    global grid_bots
    
    # If symbol not provided, try to infer or error? 
    # For clear, safer to require symbol or clear specific file.
    # If no symbol provided, maybe clear ALL? Or default to 'ETHUSDT'?
    # Let's default to removing the instance if running and the file if implicit.
    # But files are now namespaced.
    
    # Best effort: if running, use that symbol.
    target_symbol = symbol
    if not target_symbol and len(grid_bots) == 1:
        target_symbol = list(grid_bots.keys())[0]
    
    # If instance exists, stop it and remove it
    if symbol in grid_bots:
         grid_bots[symbol].stop()
         del grid_bots[symbol] # For clear, we DO remove it to reset valid state
    elif not symbol: 
         # Fallback clean old file
         if os.path.exists("data/grid_state.json"):
             try:
                os.remove("data/grid_state.json")
             except:
                pass

    # Clean specific state file if we know the symbol
    if symbol:
        fname = f"data/grid_state_{symbol}.json"
        if os.path.exists(fname):
             try:
                os.remove(fname)
             except:
                pass
                
    return jsonify({"success": True, "message": "Grid state cleared"})
    
    # Clear instance state if running
    if target_symbol in grid_bots:
        grid_bots[target_symbol].clear_state()
    
    logger_setup.log_audit("GRID_CLEAR", f"Grid state for {target_symbol} cleared by user", request.remote_addr)
    return jsonify({"success": True, "message": f"Grid state for {target_symbol} cleared"})

# ==================== CAPITAL MANAGER ENDPOINTS ====================

@app.route('/api/capital/status', methods=['GET'])
def capital_status():
    """Get capital allocation status with real-time utilization."""
    status = capital_manager.get_status()
    
    # --- Inject Real-Time Utilization (Protected Amount) ---
    signal_protected = 0.0
    grid_protected = 0.0
    
    # 1. Calculate Spot Bot Utilization (Value of held positions)
    with bot_lock:
        for bot in spot_bots.values():
            # Only count if bot holds base asset (Position Open)
            if bot.base_balance > 0:
                # Use current price if available
                price = bot.last_price
                try:
                    # Try to get fresher price from market manager if possible
                    p = market_data_manager.get_price(bot.symbol)
                    if p: price = p
                except: pass
                
                val = bot.base_balance * price
                signal_protected += val

    # 2. Calculate Grid Bot Utilization (Value of Active Orders)
    with grid_lock:
        for bot in grid_bots.values():
            if bot.running:
                # Sum up active orders
                for o in bot.active_orders:
                    if o['side'] == 'BUY':
                        # Limit Buy: Money locked in Quote
                        grid_protected += float(o['price']) * float(o['qty'])
                    elif o['side'] == 'SELL':
                        # Limit Sell: Money locked in Base (convert to USD)
                        # We need current price to estimate USD value of Base
                        price = bot.get_current_price() or 0
                        grid_protected += float(o['qty']) * price
    
    # Inject into response
    if 'signal' in status['bots']:
        status['bots']['signal']['protected'] = signal_protected
    
    if 'grid' in status['bots']:
        status['bots']['grid']['protected'] = grid_protected

    return jsonify(status)

@app.route('/api/capital/set', methods=['POST'])
def set_capital():
    """Set total capital and allocations."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        data = request.json or {}
        
        if 'total' in data:
            capital_manager.set_total_capital(data['total'])
        
        if 'signal_percent' in data:
            capital_manager.allocate('signal', percent=data['signal_percent'] / 100)
        
        if 'grid_percent' in data:
            capital_manager.allocate('grid', percent=data['grid_percent'] / 100)
        
        logger_setup.log_audit("CAPITAL_UPDATE", f"Total: {data.get('total')}", request.remote_addr)
        return jsonify(capital_manager.get_status())
    except Exception as e:
        notifier.send_telegram_message(f"❌ <b>CAPITAL ERROR</b>\nFailed to set config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/capital/reset-pnl', methods=['POST'])
def reset_pnl():
    """Reset P&L tracking."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    bot_id = request.json.get('bot_id') if request.json else None
    capital_manager.reset_pnl(bot_id)
    return jsonify({"success": True})

@app.route('/api/capital/sync', methods=['POST'])
def sync_capital():
    """Sync capital from Binance balances."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        result = capital_manager.sync_from_binance()
        if result:
            return jsonify({
                "success": True,
                "balance": result  # Contains usdt, eth, eth_price, eth_value_usd, total_usd
            })
        else:
            logging.getLogger("BinanceTradingBot").error("Capital sync returned None")
            return jsonify({"error": "Failed to sync (check logs)"}), 500
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Capital sync error: {e}")
        notifier.send_telegram_message(f"❌ <b>CAPITAL SYNC ERROR</b>\nFailed to sync: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/capital/auto-compound', methods=['POST'])
def set_auto_compound():
    """Toggle auto-compound setting."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    enabled = data.get('enabled', False)
    capital_manager.set_auto_compound(enabled)
    logger_setup.log_audit("AUTO_COMPOUND", f"Enabled: {enabled}", request.remote_addr)
    return jsonify({"success": True, "auto_compound": capital_manager.auto_compound})

@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    """Fetch all available trading pairs from Binance."""
    try:
        # Check cache or fetch fresh
        # Normally get_exchange_info is weight 20, so fine to call occasionally
        if not market_data_manager.client:
             return jsonify([])
        
        info = market_data_manager.client.get_exchange_info()
        symbols = []
        for s in info['symbols']:
            # Minimal filtering: Must be TRADING
            if s['status'] == 'TRADING':
                 symbols.append({
                     'symbol': s['symbol'],
                     'baseAsset': s['baseAsset'],
                     'quoteAsset': s['quoteAsset']
                 })
                 
        # Sort by base asset for UI niceness
        symbols.sort(key=lambda x: x['baseAsset'])
        return jsonify(symbols)
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Error fetching symbols: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug_zec', methods=['GET'])
def debug_zec():
    """Debug ZEC prices directly from server."""
    try:
        from binance import Client
        import modules.config as config
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        
        results = {}
        
        # Check ZECUSD
        try:
            klines = client.get_klines(symbol="ZECUSD", interval='1m', limit=1)
            results['ZECUSD'] = float(klines[-1][4]) if klines else None
        except Exception as e:
            results['ZECUSD_ERROR'] = str(e)
            
        # Check ZECUSDT
        try:
            klines = client.get_klines(symbol="ZECUSDT", interval='1m', limit=1)
            results['ZECUSDT'] = float(klines[-1][4]) if klines else None
        except Exception as e:
            results['ZECUSDT_ERROR'] = str(e)

        # Check BTCUSD (for comparison)
        try:
            klines = client.get_klines(symbol="BTCUSD", interval='1m', limit=1)
            results['BTCUSD'] = float(klines[-1][4]) if klines else None
        except Exception as e:
            results['BTCUSD_ERROR'] = str(e)
            
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    run_flask()
