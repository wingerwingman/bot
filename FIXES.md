# Recent Fixes (Session 2026-01-21)

## 1. Trade Value Logging (`Val` Field)
- **Issue**: The `Val` column in trade logs was showing Total Equity ($1000) instead of Trade Value ($20).
- **Fix**: Updated `trading_bot.py` to calculate Transaction Value (`Price * Qty`) for all Buy logs and Revenue for Sell logs.
- **Affected Files**: `modules/trading_bot.py`.

## 2. Test/Live Bot Isolation on Dashboard
- **Issue**: Test/Backtest bots were appearing on the Live Dashboard, and Live bots were appearing on the Backtest Dashboard.
- **Fix**: 
  - **LiveDashboard**: Added a filter to only show bots where `is_live=True`.
  - **Backtest/ControlPanel**: Added a check to hide bots if their running mode (`Live` vs `Test`) conflicts with the panel's mode.
- **Affected Files**: `botfrontend/src/components/LiveDashboard.js`, `botfrontend/src/components/ControlPanel.js`.

## 3. System Activity Log Spam from Backtests
- **Issue**: Backtest trades were being written to the persistent `trades_us.log` file, cluttering the system activity view.
- **Fix**: 
  - Updated `logger_setup.log_trade` to accept an `is_test` parameter.
  - Added logic to `logger_setup.py` to skip writing to `trade_logger` (file) if `is_test=True`.
  - Updated `trading_bot.py` to pass `is_test=True` for all simulation and backtest trades.
- **Affected Files**: `modules/logger_setup.py`, `modules/trading_bot.py`.

## Usage Note
**You must restart the Python server (`python main.py`) for the logging changes to take effect.**
