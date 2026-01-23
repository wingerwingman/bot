# Recent Fixes (Session 2026-01-23)

## 1. Backtest Performance Metrics (Sharpe, Profit Factor)
- **Issue**: Metrics like Sharpe Ratio, Profit Factor, and detailed Trade Journal were missing or limited for backtesting/paper trading modes, making it hard to evaluate strategy performance.
- **Fix**: Implemented full in-memory tracking of equity history and trade journal in `trading_bot.py`. Updated the backend API to return this rich data and the frontend `ControlPanel.js` to display it in a new dedicated Performance section and Trade Journal table.
- **Affected Files**: `modules/trading_bot.py`, `modules/server.py`, `botfrontend/src/components/ControlPanel.js`.

## 2. Backtest Symbol Naming Corrected
- **Issue**: When starting a backtest with a specific file (e.g., `solusdt_15m.csv`), the bot control panel would incorrectly label it as `ETHUSDT` (the default).
- **Fix**: Updated `ControlPanel.js` to automatically parse the selected filename using regex and derive the correct Base Asset (e.g., SOL) for the start payload.
- **Affected Files**: `botfrontend/src/components/ControlPanel.js`.

## 3. Max Win/Loss Streak Logic
- **Issue**: Streak stats were not updating consistently on the Spot Bot tab.
- **Fix**: Refined logic in `trading_bot.py` `update_metrics` to correctly track and persist consecutive wins/losses.
- **Affected Files**: `modules/trading_bot.py`.

## 4. Trade Value Logging (`Val` Field)
- **Issue**: The `Val` column in trade logs was showing Total Equity instead of Trade Value.
- **Fix**: Updated `trading_bot.py` to calculate Transaction Value (`Price * Qty`) for all Buy logs.
- **Affected Files**: `modules/trading_bot.py`.

## 5. Test/Live Bot Isolation on Dashboard
- **Issue**: Test/Backtest bots were appearing on the Live Dashboard, and Live bots were appearing on the Backtest Dashboard.
- **Fix**: Added strict filtering in `LiveDashboard` and `ControlPanel` to isolate bot lists based on their mode.
- **Affected Files**: `botfrontend/src/components/LiveDashboard.js`, `botfrontend/src/components/ControlPanel.js`.
