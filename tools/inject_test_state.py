import json
import os
import datetime

def create_test_state():
    """创建一个模拟的 live trading restoration state file."""
    
    # 模拟数据
    symbol = "ETHUSDT"
    filename = f"data/state_live_{symbol}.json"
    
    state = {
        'symbol': symbol,
        'quote_asset': 'USDT',
        'base_asset': 'ETH',
        'bought_price': 3050.00,  # Simulate we bought at $3050
        'base_balance_at_buy': 0.5, # We hold 0.5 ETH
        'position_size_percent': 25,
        'last_update': datetime.datetime.now().isoformat(),
        # Metrics to restore
        'total_trades': 10,
        'winning_trades': 6,
        'gross_profit': 150.00,
        'gross_loss': 40.00,
        'peak_balance': 1110.00,
        'max_drawdown': 0.05
    }
    
    os.makedirs('data', exist_ok=True)
    
    with open(filename, 'w') as f:
        json.dump(state, f, indent=2)
        
    print(f"✅ Created test state file: {filename}")
    print("Now run the bot in LIVE mode (ETH/USDT) to see it restore this session!")

if __name__ == "__main__":
    create_test_state()
