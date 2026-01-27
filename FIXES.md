# Recent Fixes (Session 2026-01-27)

## 1. Spot Bot "Stopped" / "Looking for Entry" Discrepancy
- **Issue**: API responses containing `NaN` (from RSI or Volatility) were invalid JSON. This caused the Frontend to receive raw strings instead of objects, breaking the dashboard status and "Protected" amount display.
- **Fix**: 
    - **Backend**: Sanitized `NaN` values in `server.py` (defaulting to 0.0 or 50.0).
    - **Frontend**: Implemented recursive `JSON.parse` in `LiveDashboard.js` to handle any level of string nesting.
- **Affected Files**: `modules/server.py`, `botfrontend/src/components/LiveDashboard.js`.

## 2. Heartbeat Crash (`UnboundLocalError`)
- **Issue**: Log message in heartbeat loop referenced `sl_price` before it was assigned.
- **Fix**: Replaced with `self.current_hard_stop`.
- **Affected Files**: `modules/trading_bot.py`.

## 3. Server Startup Syntax Error
- **Issue**: Duplicate `})` closing brace in `server.py` prevented startup.
- **Fix**: Removed extra brace.
- **Affected Files**: `modules/server.py`.

---

# Previous Fixes (Session 2026-01-23)

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

## 6. Critical Bug Fixes (Code Review)
- **ATR Calculation**: Fixed a critical bug in `modules/indicators.py` where ATR was derived by dividing by `period` instead of `num_bars`, leading to incorrect volatility readings.
- **Race Condition in State Saving**: Implemented atomic file writing (`write to tmp` -> `rename`) in `trading_bot.py`'s `save_state` method to prevent data corruption during crashes or interruptions.
- **Server Error Handling**: Fixed a potential `NameError` in `server.py`'s `/api/metrics` endpoint by initializing the `bot` variable correctly.
- **Frontend Configuration Refactor**: Centralized `API_BASE` in `config.js` and updated all frontend components (`ControlPanel`, `LiveDashboard`, etc.) to import it, improving maintainability and reducing hardcoded values.
- **Code Cleanliness**: Removed inline imports in `modules/strategy.py` to improve performance and code quality.

## 7. Security & Hardening (Bot Audit)
- **Issue**: Found hardcoded API secrets in legacy test files and race conditions in the logging system.
- **Fix**: 
    - Purged secrets from `tests/verify_multibot.py`.
    - Implemented **Idempotent Logging** to prevent duplicate logs when internal threads restart.
    - Added **Log Rotation** (Max 25MB total history) to prevent infinite file growth.
    - Fixed duplicate route definitions in `server.py` that caused startup crashes.
- **Affected Files**: `modules/logger_setup.py`, `modules/server.py`, `tests/verify_multibot.py`.

## 8. UI Privacy & Usability
- **Issue**: "Total Capital" and allocation sliders were always visible, cluttering the view and exposing financial data on stream.
- **Fix**: Implemented a **"Edit Capital" Toggle**. By default, total equity, auto-compound settings, and allocation sliders are hidden.
- **Affected Files**: `botfrontend/src/components/CapitalPanel.js`.
