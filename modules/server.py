from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import time
import os
import glob
from . import config
from .trading_bot import BinanceTradingBot
from . import indicators
from . import logger_setup

# Initialize logger immediately so errors are captured even if bot isn't running
logger_setup.setup_logger()

app = Flask(__name__)
CORS(app)

# Global bot instance
bot_instance = None
bot_lock = threading.Lock()
cached_client = None

def run_flask():
    """Run Flask in production-safe mode."""
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)  # Only show warnings/errors, not every request
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

def start_server_standalone():
    """Start the Flask server in a standalone thread (no bot yet)."""
    server_thread = threading.Thread(target=run_flask, daemon=True)
    server_thread.start()
    print("API Server running at http://localhost:5000")

# Admin Credentials
ADMIN_USER = "admin"
ADMIN_PASS = "Flamingo79*"
ADMIN_TOKEN = "secret-admin-token-12345" # Simple static token for this setup

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
        return jsonify({"success": True, "token": ADMIN_TOKEN})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/status', methods=['GET'])
def get_status():
    global bot_instance
    
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
    
    if not bot_instance:
        # Return live prices and volatility even when idle
        eth_price, btc_price, volatility = get_market_data()
        return jsonify({
            "status": "idle", 
            "running": False, 
            "mode": None,
            "eth_price": eth_price,
            "btc_price": btc_price,
            "volatility": volatility,
            "current_price": None,
            "balances": {}
        })
    
    
    # Get current price
    current_price = None
    eth_price, btc_price = None, None
    
    try:
        if bot_instance.is_live_trading:
            ticker = bot_instance.client.get_symbol_ticker(symbol=bot_instance.symbol)
            current_price = float(ticker['price'])
            # Also fetch ETH and BTC prices
            eth_price, btc_price, _ = get_market_data()
        else:
            current_price = bot_instance.last_price
            # For test mode, still try to get live prices for display
            eth_price, btc_price, _ = get_market_data()
    except Exception as e:
        print(f"Error in get_status: {e}")
        current_price = bot_instance.last_price
    
    # Get strategy settings from bot
    strategy_settings = {}
    volatility = None
    if hasattr(bot_instance, 'strategy'):
        s = bot_instance.strategy
        strategy_settings = {
            "rsi_threshold": getattr(s, 'rsi_threshold_buy', 40),
            "stop_loss_percent": getattr(s, 'stop_loss_percent', 0.02) * 100,
            "trailing_stop_percent": getattr(s, 'sell_percent', 0.03) * 100,
        }
        volatility = getattr(s, 'current_volatility', None)
    
    return jsonify({
        "status": "online",
        "running": bot_instance.running,
        "mode": "Live" if bot_instance.is_live_trading else "Test",
        "symbol": getattr(bot_instance, 'symbol', 'N/A'),
        "current_price": current_price,
        "eth_price": eth_price,
        "btc_price": btc_price,
        "volatility": volatility,
        "position_size_percent": getattr(bot_instance, 'position_size_percent', 0.25) * 100,
        "strategy_settings": strategy_settings,
        "final_balance": getattr(bot_instance, 'final_balance', None),
        "total_return": getattr(bot_instance, 'total_return', None),
        "finished": getattr(bot_instance, 'finished_data', False),
        "balances": {
            "quote": bot_instance.quote_balance,
            "base": bot_instance.base_balance,
            "quote_asset": bot_instance.quote_asset,
            "base_asset": bot_instance.base_asset,
            "base_usd_value": (bot_instance.base_balance * current_price) if current_price else 0
        }
    })

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    global bot_instance
    
    # If bot is running, return live metrics
    if bot_instance:
        win_rate = (bot_instance.winning_trades / bot_instance.total_trades * 100) if bot_instance.total_trades > 0 else 0.0
        profit_factor = (bot_instance.gross_profit / bot_instance.gross_loss) if bot_instance.gross_loss > 0 else 999.0

        return jsonify({
            "total_trades": bot_instance.total_trades,
            "winning_trades": bot_instance.winning_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": bot_instance.max_drawdown,
            "peak_balance": bot_instance.peak_balance,
            "source": "live"
        })
    
    # No bot running - try to read from saved state files
    try:
        import json
        import glob
        
        # Only look for LIVE state files (not test)
        state_files = glob.glob('data/state_live_*.json')
        if state_files:
            # Find the most recently modified state file
            state_files.sort(key=os.path.getmtime, reverse=True)
            with open(state_files[0], 'r') as f:
                state = json.load(f)
            
            total = state.get('total_trades', 0)
            wins = state.get('winning_trades', 0)
            win_rate = (wins / total * 100) if total > 0 else 0.0
            gross_profit = state.get('gross_profit', 0)
            gross_loss = state.get('gross_loss', 0)
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
            
            return jsonify({
                "total_trades": total,
                "winning_trades": wins,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "max_drawdown": state.get('max_drawdown', 0),
                "peak_balance": state.get('peak_balance', 0),
                "source": "saved_live",
                "symbol": state.get('symbol', 'Unknown')
            })
    except Exception as e:
        print(f"Error reading saved metrics: {e}")
    
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
        
    global bot_instance
    
    with bot_lock:
        if bot_instance and bot_instance.running:
            return jsonify({"error": "Bot is already running"}), 400
        
        data = request.json or {}
        mode = data.get('mode', 'test')  # 'live' or 'test'
        filename = data.get('filename')  # For test mode
        quote_asset = data.get('quote_asset', 'USDT')  # Currency to buy with
        base_asset = data.get('base_asset', 'ETH')     # Crypto to trade
        position_size = data.get('position_size_percent', 25) / 100
        
        # Strategy Parameters
        rsi_threshold = data.get('rsi_threshold', 40)
        stop_loss = data.get('stop_loss_percent', 2) / 100
        trailing_stop = data.get('trailing_stop_percent', 3) / 100
        dynamic_settings = data.get('dynamic_settings', False)
        
        is_live = (mode.lower() == 'live')
        
        # For test mode, we need a valid filename
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
        
        # Explicitly clear old instance reference
        bot_instance = None
        
        try:
            bot_instance = BinanceTradingBot(
                is_live_trading=is_live, 
                filename=filename,
                quote_asset=quote_asset,
                base_asset=base_asset,
                position_size_percent=position_size,
                rsi_threshold=rsi_threshold,
                stop_loss=stop_loss,
                trailing_stop=trailing_stop,
                dynamic_settings=dynamic_settings,
                resume_state=resume_session
            )
            bot_instance.start()
            return jsonify({"success": True, "mode": mode, "symbol": bot_instance.symbol})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the running bot."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
        
    global bot_instance
    
    with bot_lock:
        if not bot_instance:
            return jsonify({"error": "No bot is running"}), 400
        
        if bot_instance.running:
            bot_instance.stop()
        
        bot_instance = None
        return jsonify({"success": True})

@app.route('/api/errors', methods=['GET'])
def get_errors():
    """Returns the list of recent errors."""
    try:
        from .logger_setup import recent_errors
        return jsonify({"errors": list(recent_errors)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/errors/clear', methods=['POST'])
def clear_errors_log():
    """Clears the error log buffer."""
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    logger_setup.clear_errors()
    return jsonify({"success": True})

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

if __name__ == '__main__':
    run_flask()
