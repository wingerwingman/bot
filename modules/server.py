from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import time
import os
import glob
from . import config
from .trading_bot import BinanceTradingBot

app = Flask(__name__)
CORS(app)

# Global bot instance
bot_instance = None
bot_lock = threading.Lock()

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

# ===================== API ENDPOINTS =====================

@app.route('/api/status', methods=['GET'])
def get_status():
    global bot_instance
    if not bot_instance:
        return jsonify({"status": "idle", "running": False, "mode": None})
    
    return jsonify({
        "status": "online",
        "running": bot_instance.running,
        "mode": "Live" if bot_instance.is_live_trading else "Test",
        "symbol": getattr(bot_instance, 'symbol', 'N/A'),
        "current_price": bot_instance.last_price,
        "balances": {
            "quote": bot_instance.quote_balance,
            "base": bot_instance.base_balance,
            "quote_asset": bot_instance.quote_asset,
            "base_asset": bot_instance.base_asset
        }
    })

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    global bot_instance
    if not bot_instance:
        return jsonify({})
    
    win_rate = (bot_instance.winning_trades / bot_instance.total_trades * 100) if bot_instance.total_trades > 0 else 0.0
    profit_factor = (bot_instance.gross_profit / bot_instance.gross_loss) if bot_instance.gross_loss > 0 else 999.0

    return jsonify({
        "total_trades": bot_instance.total_trades,
        "winning_trades": bot_instance.winning_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": bot_instance.max_drawdown,
        "peak_balance": bot_instance.peak_balance
    })

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
    global bot_instance
    
    with bot_lock:
        if bot_instance and bot_instance.running:
            return jsonify({"error": "Bot is already running"}), 400
        
        data = request.json or {}
        mode = data.get('mode', 'test')  # 'live' or 'test'
        filename = data.get('filename')  # For test mode
        quote_asset = data.get('quote_asset', 'USDT')  # Currency to buy with
        base_asset = data.get('base_asset', 'ETH')     # Crypto to trade
        
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
        
        try:
            bot_instance = BinanceTradingBot(
                is_live_trading=is_live, 
                filename=filename,
                quote_asset=quote_asset,
                base_asset=base_asset
            )
            bot_instance.start()
            return jsonify({"success": True, "mode": mode, "symbol": bot_instance.symbol})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the running bot."""
    global bot_instance
    
    with bot_lock:
        if not bot_instance:
            return jsonify({"error": "No bot is running"}), 400
        
        if bot_instance.running:
            bot_instance.stop()
        
        bot_instance = None
        return jsonify({"success": True})

if __name__ == '__main__':
    run_flask()
