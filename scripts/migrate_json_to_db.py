import json
import os
import glob
import json
import os
import glob
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.database import engine, db_session
from modules.models import CapitalState, BotState, GridState

def migrate_capital():
    print("Migrating Capital State...")
    json_path = 'data/capital_state.json'
    if not os.path.exists(json_path):
        print(f"No capital file found at {json_path}")
        return

    with open(json_path, 'r') as f:
        data = json.load(f)

    session = db_session()
    # Singleton ID 1
    state = session.query(CapitalState).filter_by(id=1).first()
    if not state:
        state = CapitalState(id=1)
        session.add(state)

    state.total_capital = data.get('total_capital', 0.0)
    state.allocations = data.get('allocations', {})
    state.pnl = data.get('pnl', {})  # Critical for "Combined Net Profit"
    state.auto_compound = data.get('auto_compound', False)
    
    session.commit()
    print(f"✅ Capital State migrated (Total Cap: {state.total_capital})")
    session.close()

def migrate_spot_bots():
    print("Migrating Spot Bots...")
    files = glob.glob('data/state_live_*.json')
    session = db_session()

    for file_path in files:
        filename = os.path.basename(file_path)
        # Format: state_live_ETHUSDT.json
        symbol = filename.replace('state_live_', '').replace('.json', '')
        
        print(f"Processing Spot Bot: {symbol}...")
        
        with open(file_path, 'r') as f:
            data = json.load(f)

        # Upsert
        bot_state = session.query(BotState).filter_by(symbol=symbol).first()
        if not bot_state:
            bot_state = BotState(symbol=symbol)
            session.add(bot_state)

        # Basic Stats
        bot_state.is_active = True # Assume active if file exists? Or read 'runnning'? 
        # Note: older JSON might not have 'running'. default to True if file exists.
        
        bot_state.bought_price = data.get('bought_price')
        bot_state.base_balance = data.get('base_balance_at_buy') # Important for position size
        
        # Populate Metrics JSON
        metrics = {
            'total_trades': data.get('total_trades', 0),
            'winning_trades': data.get('winning_trades', 0),
            'gross_profit': data.get('gross_profit', 0.0),
            'gross_loss': data.get('gross_loss', 0.0),
            'peak_balance': data.get('peak_balance', 0.0),
            'max_drawdown': data.get('max_drawdown', 0.0),
            'max_win_streak': data.get('max_win_streak', 0),
            'max_loss_streak': data.get('max_loss_streak', 0),
            'consecutive_wins': data.get('consecutive_wins', 0),
            'consecutive_losses': data.get('consecutive_losses', 0)
        }
        bot_state.metrics = metrics

        # Populate Config JSON
        config_data = data.get('strategy_settings', {})
        # Merge relevant top-level keys if any
        config_data.update({
            'paused': data.get('paused', False)
        })
        bot_state.configuration = config_data
        
        # Other Columns
        bot_state.peak_price = data.get('peak_price_since_buy')
        
    session.commit()
    print(f"✅ Migrated {len(files)} Spot Bots.")
    session.close()

def migrate_grid_bots():
    print("Migrating Grid Bots...")
    files = glob.glob('data/grid_state_*.json')
    session = db_session()

    for file_path in files:
        filename = os.path.basename(file_path)
        # Format: grid_state_ETHUSDT.json
        symbol = filename.replace('grid_state_', '').replace('.json', '')
        
        print(f"Processing Grid Bot: {symbol}...")
        
        with open(file_path, 'r') as f:
            data = json.load(f)

        grid_state = session.query(GridState).filter_by(symbol=symbol).first()
        if not grid_state:
            grid_state = GridState(symbol=symbol)
            session.add(grid_state)
            
        grid_state.is_active = data.get('running', False)
        grid_state.lower_bound = data.get('lower_bound')
        grid_state.upper_bound = data.get('upper_bound')
        grid_state.grid_count = data.get('grid_count')
        grid_state.total_profit = data.get('total_profit', 0.0)
        grid_state.buy_fills = data.get('buy_fills', 0)
        grid_state.sell_fills = data.get('sell_fills', 0)
        grid_state.active_orders = data.get('active_orders', [])
        
        # Config
        grid_state.configuration = {
            'capital': data.get('capital'),
            'auto_rebalance_enabled': data.get('auto_rebalance_enabled'),
            'volatility_spacing_enabled': data.get('volatility_spacing_enabled'),
            'paused': data.get('paused')
        }
        
        # Metrics
        grid_state.metrics = {
            'total_fees': data.get('total_fees', 0.0),
            'rebalance_count': data.get('rebalance_count', 0),
            'filled_orders': data.get('filled_orders', [])
        }
        
    session.commit()
    print(f"✅ Migrated {len(files)} Grid Bots.")
    session.close()

if __name__ == "__main__":
    try:
        migrate_capital()
        migrate_spot_bots()
        migrate_grid_bots()
        print("\n🎉 Migration Complete!")
    except Exception as e:
        print(f"\n❌ Migration Failed: {e}")
