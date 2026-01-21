from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import time
import os
import glob
import logging
import json
from . import config
from .trading_bot import BinanceTradingBot
from . import indicators
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
bot_lock = threading.Lock()

grid_bots = {} # Key: symbol -> GridBot
grid_lock = threading.Lock()
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
    print("API Server running at http://localhost:5050")

# Admin Credentials
# Admin Credentials (Loaded from Config/Env)
ADMIN_USER = config.ADMIN_USER
ADMIN_PASS = config.ADMIN_PASS
ADMIN_TOKEN = config.ADMIN_TOKEN

def check_auth():
    """Checks for valid auth token in headers."""
    token = request.headers.get('X-Auth-Token')
    return token == ADMIN_TOKEN

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
    def get_market_data():
        global cached_client
        try:
            from binance import Client
            if cached_client is None:
                 cached_client = Client(config.API_KEY, config.API_SECRET, tld='us')
            
            eth_ticker = cached_client.get_symbol_ticker(symbol='ETHUSDT')
            eth_price = float(eth_ticker['price'])
            
            btc_ticker = cached_client.get_symbol_ticker(symbol='BTCUSDT')
            btc_price = float(btc_ticker['price'])
            
            # Calculate Volatility (14-day ATR)
            klines = cached_client.get_historical_klines("ETHUSDT", Client.KLINE_INTERVAL_1DAY, "14 day ago UTC")
            atr = indicators.calculate_volatility_from_klines(klines, 14)
            volatility = atr / eth_price if eth_price else 0
            
            return eth_price, btc_price, volatility
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return None, None, None
    
    # If specific symbol requested, return details for that bot
    req_symbol = request.args.get('symbol')
    req_type = request.args.get('type', 'spot')
    
    # Aggregate all running bots for the summary list
    active_bots = []
    
    # Add Spot Bots
    with bot_lock:
        for symbol, bot in spot_bots.items():
            net_profit = bot.gross_profit - bot.gross_loss
            active_bots.append({
                "id": f"spot_{symbol}",
                "symbol": symbol,
                "type": "spot",
                "status": "running" if bot.running else "stopped",
                "profit": net_profit,
                "is_live": bot.is_live_trading
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
                "is_live": bot.is_live
            })

    # Basic market prices (ETH/BTC) for dashboard header
    eth_price, btc_price, vol = get_market_data()
    
    # If a specific bot status is requested (for Bot Panel details)
    if req_symbol and req_type == 'spot':
        bot = spot_bots.get(req_symbol)
        if not bot:
             # Try to find any spot bot if none specified? No, strict match.
             return jsonify({"status": "idle", "running": False, "symbol": req_symbol})
        
        # ... Reuse logic to extract detailed metrics for ONE bot ...
        # Calculate Realtime Metrics
        net_profit = bot.gross_profit - bot.gross_loss
        realtime_metrics = {
            "active_orders": 1 if bot.bought_price else 0,
            "buy_fills": bot.total_trades + (1 if bot.bought_price else 0),
            "sell_fills": bot.total_trades,
            "total_fees": getattr(bot, 'total_fees', 0.0),
            "net_profit": net_profit
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
            }
            volatility = getattr(s, 'current_volatility', None)

        try:
            if bot.is_live_trading:
                ticker = bot.client.get_symbol_ticker(symbol=bot.symbol)
                current_price = float(ticker['price'])
            else:
                current_price = bot.last_price
        except:
            current_price = bot.last_price

        return jsonify({
            "status": "online",
            "running": bot.running,
            "mode": "Live" if bot.is_live_trading else "Test",
            "realtime_metrics": realtime_metrics,
            "symbol": bot.symbol,
            "current_price": current_price,
            "eth_price": eth_price,
            "btc_price": btc_price,
            "volatility": volatility,
            "position_size_percent": getattr(bot, 'position_size_percent', 0.25) * 100,
            "dynamic_settings": getattr(bot, 'dynamic_settings', False),
            "dca_enabled": getattr(bot.strategy, 'dca_enabled', False) if hasattr(bot, 'strategy') else False,
            "strategy_settings": strategy_settings,
            "final_balance": getattr(bot, 'final_balance', None),
            "total_return": getattr(bot, 'total_return', None),
            "finished": getattr(bot, 'finished_data', False),
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
                "current_price": current_price
            },
            # Also include the full list for the generic updater? 
            # Ideally the frontend polls /status for the list and /status?symbol=X for details.
            # But the frontend expects 'active_bots' in the main response potentially.
        })

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
    
    # If specific running bot requested
    if symbol:
        bot = spot_bots.get(symbol)
        if bot:
            win_rate = (bot.winning_trades / bot.total_trades * 100) if bot.total_trades > 0 else 0.0
            profit_factor = (bot.gross_profit / bot.gross_loss) if bot.gross_loss > 0 else 999.0
            return jsonify({
                "total_trades": bot.total_trades,
                "winning_trades": bot.winning_trades,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "max_drawdown": bot.max_drawdown,
                "peak_balance": bot.peak_balance,
                "source": "live",
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

@app.route('/api/logs/audit/clear', methods=['POST'])
def clear_audit_logs():
    """Clears the audit logs."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_audit_logs()
    logger_setup.log_audit("CLEAR_LOGS", "Audit logs cleared by user", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/activity/clear', methods=['POST'])
def clear_activity_logs():
    """Clears the activity logs."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_activity_logs()
    logger_setup.log_audit("CLEAR_LOGS", "Activity logs cleared by user", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/logs/strategy/clear', methods=['POST'])
def clear_strategy_logs():
    """Clears the strategy logs."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_strategy_logs()
    logger_setup.log_audit("CLEAR_LOGS", "Strategy logs cleared by user", request.remote_addr)
    return jsonify({"success": True})

@app.route('/api/market-status', methods=['GET'])
def get_market_status():
    """Fetches market status (Price, Volatility) for a given symbol."""
    symbol = request.args.get('symbol', 'ETH')
    base_pair = f"{symbol}USDT"
    
    try:
        from binance import Client
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        try:
           price = float(client.get_symbol_ticker(symbol=base_pair)['price'])
        except Exception:
           # Fallback or error if symbol invalid
           return jsonify({"error": f"Invalid symbol: {symbol}", "symbol": symbol}), 400
        
        # Calculate Volatility (14-day ATR)
        klines = client.get_historical_klines(base_pair, Client.KLINE_INTERVAL_1DAY, "14 day ago UTC")
        atr = indicators.calculate_volatility_from_klines(klines, 14)
        
        # Normalize to percentage
        volatility = atr / price if price else 0
        
        return jsonify({
            "symbol": symbol,
            "price": price,
            "volatility": volatility
        })
    except Exception as e:
        print(f"Error fetching market status for {symbol}: {e}")
        return jsonify({"error": str(e), "symbol": symbol, "price": None, "volatility": None})

@app.route('/api/datafiles', methods=['GET'])
def get_datafiles():
    """Returns available CSV files for backtesting."""
    data_dir = os.path.join(os.getcwd(), 'data')
    if not os.path.exists(data_dir):
        return jsonify([])
    
    files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
    return jsonify(files)

@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    """Returns all available USDT trading pairs from Binance."""
    try:
        from binance import Client
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        
        exchange_info = client.get_exchange_info()
        
        # Filter for USDT pairs that are actively trading
        usdt_symbols = []
        for s in exchange_info['symbols']:
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                usdt_symbols.append({
                    'symbol': s['symbol'],
                    'baseAsset': s['baseAsset'],
                    'quoteAsset': s['quoteAsset']
                })
        
        # Sort alphabetically by base asset
        usdt_symbols.sort(key=lambda x: x['baseAsset'])
        
        return jsonify(usdt_symbols)
    except Exception as e:
        logging.getLogger("BinanceTradingBot").error(f"Error fetching symbols: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/balances', methods=['GET'])
def get_balances():
    """Returns all balances from Binance account with USD values."""
    try:
        from binance import Client
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        account_info = client.get_account()
        
        # Fetch all prices for USD conversion
        all_prices = {p['symbol']: float(p['price']) for p in client.get_all_tickers()}
        
        important = ['USDT', 'USD', 'ETH', 'BTC', 'BNB', 'SOL']
        balances = []
        
        for b in account_info['balances']:
            free = float(b['free'])
            locked = float(b['locked'])
            total = free + locked
            
            if total > 0 or b['asset'] in important:
                # Calculate USD value
                asset = b['asset']
                usd_value = 0.0
                
                if asset in ['USDT', 'USD', 'BUSD', 'USDC']:
                    usd_value = total
                elif f"{asset}USDT" in all_prices:
                    usd_value = total * all_prices[f"{asset}USDT"]
                elif f"{asset}USD" in all_prices:
                    usd_value = total * all_prices[f"{asset}USD"]
                elif f"{asset}BTC" in all_prices and 'BTCUSDT' in all_prices:
                    usd_value = total * all_prices[f"{asset}BTC"] * all_prices['BTCUSDT']
                
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
        quote_asset = data.get('quote_asset', 'USDT')  # Currency to buy with
        base_asset = data.get('base_asset', 'ETH')     # Crypto to trade
        symbol = f"{base_asset}{quote_asset}"
        
        if symbol in spot_bots and spot_bots[symbol].running:
            msg = f"Start failed: Bot for {symbol} is already active and running."
            logging.getLogger("BinanceTradingBot").error(msg)
            return jsonify({"error": msg}), 400
        
        # If exists but stopped, we will overwrite it below.
        
        mode = data.get('mode', 'test')  # 'live' or 'test'
        filename = data.get('filename')  # For test mode
        position_size = data.get('position_size_percent', 25) / 100
        
        # Strategy Parameters
        rsi_threshold = data.get('rsi_threshold', 40)
        stop_loss = data.get('stop_loss_percent', 2) / 100
        trailing_stop = data.get('trailing_stop_percent', 3) / 100
        dynamic_settings = data.get('dynamic_settings', False)
        dca_enabled = data.get('dca_enabled', True)
        dca_rsi_threshold = data.get('dca_rsi_threshold', 30)
        
        is_live = (mode.lower() == 'live')
        
        if not is_live:
            if not filename:
                return jsonify({"error": "Filename required for test mode"}), 400
            data_dir = os.path.join(os.getcwd(), 'data')
            full_path = os.path.join(data_dir, filename)
            if not os.path.exists(full_path):
                return jsonify({"error": f"File not found: {filename}"}), 400
            filename = full_path
        else:
            filename = None
        
        resume_session = data.get('resumeSession', True)
        
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
                dca_rsi_threshold=dca_rsi_threshold
            )
            bot.start()
            spot_bots[symbol] = bot
            logger_setup.log_audit("START_BOT", f"Mode: {mode}, Symbol: {base_asset}", request.remote_addr)
            return jsonify({"success": True, "mode": mode, "symbol": bot.symbol})
        except Exception as e:
            notifier.send_telegram_message(f"❌ <b>BOT START ERROR ({symbol})</b>\nFailed to start: {e}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the running bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    symbol = data.get('symbol')
        
    global spot_bots
    
    try:
        with bot_lock:
            if not symbol:
                 # If only 1 bot running, stop it? Or strictly require symbol?
                 # Strict is safer for multi-bot.
                 # Actually, let's just loop and stop ALL if no symbol? 
                 # Or just error. Let's error.
                 if len(spot_bots) == 1:
                     symbol = list(spot_bots.keys())[0]
                 else:
                     return jsonify({"error": "Symbol required to stop specific bot"}), 400
            
            bot = spot_bots.get(symbol)
            if not bot:
                 return jsonify({"error": f"No bot running for symbol {symbol}"}), 400
            
            if bot.running:
                bot.stop()
            
            # Do NOT delete the bot, keep it in memory as 'stopped'
            # del spot_bots[symbol]
            
            logger_setup.log_audit("STOP_BOT", f"Bot {symbol} stopped by user", request.remote_addr)
            return jsonify({"success": True})
    except Exception as e:
        notifier.send_telegram_message(f"❌ <b>BOT STOP ERROR</b>\nFailed to stop: {e}")
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
            wins = sum(1 for t in trades if t.get('action') == 'SELL' and t.get('pnl_amount', 0) >= 0)
            losses = sum(1 for t in trades if t.get('action') == 'SELL' and t.get('pnl_amount', 0) < 0)
            total_sells = wins + losses
            
            summary['total_trades'] = len([t for t in trades if t.get('action') == 'SELL'])
            summary['winning_trades'] = wins
            summary['losing_trades'] = losses
            summary['win_rate'] = round((wins / total_sells * 100), 1) if total_sells > 0 else 0
        
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

@app.route('/api/config/update', methods=['POST'])
def update_config():
    """Updates configuration of the running bot."""
    data = request.json
    symbol = data.get('symbol')
    
    global spot_bots
    
    if len(spot_bots) == 1 and not symbol:
        symbol = list(spot_bots.keys())[0]
    
    bot = spot_bots.get(symbol)
    if not bot or not bot.running:
        return jsonify({"error": "Bot is not running"}), 400
        
    try:
        # Update Resume State
        if 'resume_state' in data:
            bot.resume_state = bool(data['resume_state'])
            print(f"[{symbol}] Config Update: Resume State set to {bot.resume_state}")
            logger_setup.log_audit("CONFIG_CHANGE", f"Resume Session: {bot.resume_state}", request.remote_addr)
            
        # Update Dynamic Settings Toggle
        if 'dynamic_settings' in data:
            bot.dynamic_settings = bool(data['dynamic_settings'])
            print(f"[{symbol}] Config Update: Dynamic Settings set to {bot.dynamic_settings}")
            logger_setup.log_audit("CONFIG_CHANGE", f"Dynamic Settings: {bot.dynamic_settings}", request.remote_addr)
            
        # Update DCA Toggle
        if 'dca_enabled' in data:
            if hasattr(bot.strategy, 'dca_enabled'):
                bot.strategy.dca_enabled = bool(data['dca_enabled'])
                print(f"[{symbol}] Config Update: Defense Mode (DCA) set to {bot.strategy.dca_enabled}")
                logger_setup.log_audit("CONFIG_CHANGE", f"DCA Enabled: {bot.strategy.dca_enabled}", request.remote_addr)
            
        return jsonify({
            "success": True, 
            "resume_state": bot.resume_state,
            "dynamic_settings": bot.dynamic_settings,
            "dca_enabled": getattr(bot.strategy, 'dca_enabled', False)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        
        # BALANCE VALIDATION for Live Mode (includes ETH holdings)
        if is_live:
            try:
                from binance import Client
                client = Client(config.API_KEY, config.API_SECRET, tld='us')
                account = client.get_account()
                usdt_balance = 0.0
                eth_balance = 0.0
                
                for b in account['balances']:
                    if b['asset'] == 'USDT':
                        usdt_balance = float(b['free']) + float(b['locked'])
                    elif b['asset'] == 'ETH':
                        eth_balance = float(b['free']) + float(b['locked'])
                
                # Get ETH price to calculate total capital
                eth_price = 0.0
                try:
                    ticker = client.get_symbol_ticker(symbol='ETHUSDT')
                    eth_price = float(ticker['price'])
                except:
                    pass
                
                eth_value_usd = eth_balance * eth_price
                total_capital = usdt_balance + eth_value_usd
                
                if total_capital < capital:
                    msg = f"Insufficient capital. Required: ${capital:.2f}, Available: ${total_capital:.2f} (USDT: ${usdt_balance:.2f} + ETH: ${eth_value_usd:.2f})"
                    logging.getLogger("BinanceTradingBot").error(msg)
                    return jsonify({"error": msg}), 400
                    
            except Exception as e:
                msg = f"Failed to check balance: {e}"
                logging.getLogger("BinanceTradingBot").error(msg)
                return jsonify({"error": msg}), 500
        
        try:
            bot = GridBot(
                symbol=symbol,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                grid_count=grid_count,
                capital=capital,
                is_live=is_live,
                resume_state=resume_state
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
    """Get capital allocation status."""
    return jsonify(capital_manager.get_status())

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

if __name__ == '__main__':
    run_flask()
