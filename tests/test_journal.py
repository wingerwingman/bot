from modules import logger_setup
import datetime

print("Injecting test data into Trade Journal...")

# Create a sample trade entry
sample_trade = {
    'action': 'BUY',
    'symbol': 'BTCUSDT',
    'price': 42000.50,
    'qty': 0.1,
    'total_value': 4200.05,
    'entry_reason': 'Test Injection',
    'timestamp': datetime.datetime.now().isoformat(),
    'indicators': {
        'rsi': 35.5,
        'volatility': 1.2,
        'fear_greed': 45
    },
    'pnl_amount': 0, # Buy has no PnL
    'balance_after': 1000.0
}

# Create a sample sell to generate PnL stats
sample_sell = {
    'action': 'SELL',
    'symbol': 'BTCUSDT',
    'price': 42500.00,
    'qty': 0.1,
    'total_value': 4250.00,
    'exit_reason': 'Test Exit',
    'pnl_amount': 49.95,
    'pnl_percent': 1.19,
    'timestamp': datetime.datetime.now().isoformat(),
    'indicators': {
        'rsi': 65.0,
        'volatility': 1.1
    },
    'session_stats': {
        'win_rate': 100.0,
        'net_pnl': 49.95
    }
}

# Log them
logger_setup.log_trade_journal(sample_trade)
print("Logged BUY entry.")
logger_setup.log_trade_journal(sample_sell)
print("Logged SELL entry.")

# Log equity snapshot for Sharpe Ratio (need at least 2 for it to calculate eventually)
logger_setup.log_equity_snapshot(1049.95, 1.19)
print("Logged Equity snapshot.")

print("Done! Refresh your dashboard.")
