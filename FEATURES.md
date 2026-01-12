# CryptoBot - Features & File Structure

## 📂 Project File Tree
```
CryptoBot/
├── main.py                    # Entry point. Handles CLI args and starts Server/Bot.
├── docker-compose.yml         # Container orchestration config.
├── Dockerfile                 # Docker build definition.
├── requirements.txt           # Python dependencies.
├── .env                       # Environment variables (API Keys).
│
├── modules/                   # 🧠 Backend Logic
│   ├── trading_bot.py         # CORE: Main loop, Order execution, State management, Restoration.
│   ├── server.py              # API: Flask server, Endpoints for Frontend, Status polling.
│   ├── strategy.py            # LOGIC: Signal generation (RSI/MACD/Bollinger), Buy/Sell rules.
│   ├── indicators.py          # MATH: Technical analysis calculations (ATR, RSI, etc).
│   ├── logger_setup.py        # LOGS: Logging configuration, Handlers, Formatting.
│   └── config.py              # CONFIG: Loads env vars and constants.
│
├── botfrontend/               # 💻 Frontend UI (React)
│   └── src/
│       └── components/
│           ├── App.js                 # Main UI Container & Routing.
│           ├── LiveDashboard.js       # Real-time Charts, Metrics, Log Tabs ("System" / "Strategy").
│           ├── ControlPanel.js        # Start/Stop buttons, Dynamic Settings Display, Restore Toggle.
│           └── BacktestDashboard.js   # Historical simulation interface.
│
├── data/                      # 💾 Persistence
│   └── state_live_*.json      # Session state files (Position, Entry Price, Metrics) for recovery.
│
└── logs/                      # 📝 Log Storage
    └── trading.log            # Full debug logs.
```

## 🚀 Feature Map

| Feature Category | Feature Name | Primary Implemented File(s) | Description |
| :--- | :--- | :--- | :--- |
| **Core Trading** | **Live Trading Loop** | `modules/trading_bot.py` | Main `run()` loop handles price checks, order execution. |
| | **Session Restoration** | `modules/trading_bot.py` | `load_state()`, `save_state()` handle crash recovery. |
| | **Precision Handling** | `modules/trading_bot.py` | `fetch_exchange_filters()` ensures API compliance. |
| **Strategy** | **Dynamic Auto-Tuning** | `modules/trading_bot.py` | Updates RSI/SL/Trail based on Volatility (ATR). |
| | **Signal Logic** | `modules/strategy.py` | `check_buy_signal`, `check_sell_signal` methods. |
| | **Volatility Calc** | `modules/indicators.py` | `calculate_volatility_from_klines`. |
| **Frontend UI** | **Real-time Dashboard** | `LiveDashboard.js` | Displays Price, Balance, PnL, Active Position. |
| | **Log Tabs** | `LiveDashboard.js` | Separates "System Activity" from "Strategy Tuning". |
| | **Remote Control** | `ControlPanel.js` | Start/Stop bot via API calls. |
| **System** | **Logging Architecture** | `modules/logger_setup.py` | Handles distinct log streams (System vs Strategy). |
| | **API Server** | `modules/server.py` | Flask API serving data to React Frontend. |
| | **Dockerization** | `Dockerfile` | Container setup for deployment. |

## 🛠️ Key Module Details

### `modules/trading_bot.py`
The heart of the system. It initializes the `Binance` client, manages the websocket connection (or polling loop), and executes trades. It owns the `Strategy` instance and feeds it price data.

### `modules/strategy.py`
Pure logic component. Contains no trading execution code. It only looks at price history and returns `True`/`False` for Buy/Sell signals.

### `modules/server.py`
The bridge between the Python bot and the React UI. It runs a background thread to keep the bot alive and serves endpoints like `/api/status`, `/api/start`, and `/api/logs`.

### `botfrontend/src/components/LiveDashboard.js`
The main "Cockpit". It polls the server every few seconds to update charts and tables. It contains the logic to separate logs into the two distinct tabs.

## 📊 Data Sources & Strategy Logic

### 1. Market Data
*   **Price Feed**: Live ticker data from **Binance.US API** (`get_symbol_ticker`).
*   **Volatility**: Calculated locally using **14-day ATR (Average True Range)**.
    *   *Source*: 14 days of daily Klines (candlesticks) from Binance.
    *   *Usage*: Determines Dynamic Stop Loss and Trailing Stop percentages.

### 2. Sentiment Data
*   **Fear & Greed Index**: Fetched from [Alternative.me API](https://api.alternative.me/fng/).
    *   *Usage*: Logged for user reference (currently). Can be used to adjust buy aggression.

### 3. Technical Indicators (pandas_ta)
*   **RSI (Relative Strength Index)**: Used for Buy signals (Default < 40).
*   **MACD (Moving Average Convergence Divergence)**: Used for momentum confirmation.
*   **MA (Moving Averages)**:
    *   **200 MA**: Trend Filter (Buy only if Price > 200 MA).
    *   **Fast/Slow MA**: Crossover logic.
