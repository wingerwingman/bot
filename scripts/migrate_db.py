import sys
import os
import json
import csv
from datetime import datetime

# Fix path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.database import init_db, db_session
from modules.models import Trade, BotState, GridState, CapitalState

def parse_float(val):
    try:
        return float(val)
    except:
        return 0.0

def migrate():
    print("Starting Database Migration...")
    
    # 1. Initialize DB (Create Tables)
    init_db()
    session = db_session()
    
    # 2. Migrate Bot State (bot_state.json)
    if os.path.exists("data/bot_state.json"):
        print("Migrating Bot State...")
        try:
            with open("data/bot_state.json", 'r') as f:
                data = json.load(f)
                # Handle old single-bot format vs new multi-bot
                # If it's a list or dict of bots?
                # Usually bot_state.json was single. Let's assume single for 'ETHUSDT' default or check structure.
                # If it is a flat dict with 'symbol', it's one bot.
                if isinstance(data, dict):
                    symbol = data.get('symbol', 'ETHUSDT')
                    bot_state = BotState(
                        symbol=symbol,
                        is_active=False, # Reset to false for safety
                        base_balance=parse_float(data.get('base_balance')),
                        quote_balance=parse_float(data.get('quote_balance')),
                        bought_price=parse_float(data.get('bought_price')),
                        dca_count=data.get('dca_count', 0),
                        peak_price=parse_float(data.get('peak_price_since_buy')),
                        stop_loss_price=parse_float(data.get('stop_loss_price')),
                        last_volatility=parse_float(data.get('last_volatility'))
                    )
                    session.merge(bot_state)
        except Exception as e:
            print(f"Error migrating bot_state: {e}")

    # 3. Migrate Grid State (grid_state.json)
    if os.path.exists("data/grid_state.json"):
        print("Migrating Grid State...")
        try:
            with open("data/grid_state.json", 'r') as f:
                data = json.load(f)
                # Check for list of grids or single
                # Assuming single dict or keyed by symbol
                # Standard format for grid bot persistence?
                # It's likely a dict with 'orders', 'profit', etc.
                symbol = data.get('symbol', 'ETHUSDT')
                grid_state = GridState(
                    symbol=symbol,
                    is_active=False,
                    lower_bound=parse_float(data.get('lower_bound')),
                    upper_bound=parse_float(data.get('upper_bound')),
                    grid_count=data.get('grid_count', 0),
                    total_profit=parse_float(data.get('total_profit')),
                    buy_fills=data.get('buy_fills', 0),
                    sell_fills=data.get('sell_fills', 0),
                    active_orders=data.get('orders', [])
                )
                session.merge(grid_state)
        except Exception as e:
             print(f"Error migrating grid_state: {e}")

    # 4. Migrate Capital State (capital_state.json)
    if os.path.exists("data/capital_state.json"):
        print("Migrating Capital State...")
        try:
            with open("data/capital_state.json", 'r') as f:
                data = json.load(f)
                cap_state = CapitalState(
                    id=1,
                    total_capital=parse_float(data.get('total_capital', 1000)),
                    allocations=data.get('allocations', {}),
                    binance_usdt=parse_float(data.get('binance_usdt')),
                    binance_total_usd=parse_float(data.get('binance_total_usd')),
                    auto_compound=data.get('auto_compound', False)
                )
                session.merge(cap_state)
        except Exception as e:
             print(f"Error migrating capital_state: {e}")
             
    # 5. Migrate Trades (trade_journal.json)
    if os.path.exists("logs/trade_journal.json"):
        print("Migrating Trade Journal...")
        try:
            with open("logs/trade_journal.json", 'r', encoding='utf-8') as f:
                journal = json.load(f)
                count = 0
                for entry in journal:
                    # Convert ISO timestamp to datetime
                    ts_str = entry.get('timestamp')
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except:
                        ts = datetime.utcnow()
                        
                    trade = Trade(
                        symbol=entry.get('symbol', 'ETHUSDT'),
                        side=entry.get('action'),
                        price=parse_float(entry.get('price')),
                        quantity=parse_float(entry.get('qty')),
                        total_value=parse_float(entry.get('total_value')),
                        fee=parse_float(entry.get('fee')),
                        timestamp=ts,
                        reason=entry.get('entry_reason') or entry.get('exit_reason'),
                        strategy_data=entry.get('indicators'),
                        pnl_amount=parse_float(entry.get('pnl_amount')),
                        pnl_percent=parse_float(entry.get('pnl_percent'))
                    )
                    session.add(trade)
                    count += 1
                print(f"Imported {count} trades from journal.")
        except Exception as e:
            print(f"Error migrating journal: {e}")
            
    # 6. Commit
    session.commit()
    print("Migration Complete! Database: data/bot_data.db")
    session.close()

if __name__ == "__main__":
    migrate()
