# CryptoBot - Features & File Structure

## 📂 Project File Tree
```
CryptoBot/
├── main.py                    # Entry point. Handles CLI args and starts Server/Bot.
├── docker-compose.yml         # Container orchestration config.
├── Dockerfile                 # Docker build definition.
├── requirements.txt           # Python dependencies.
├── .env                       # Environment variables (API Keys, Telegram, Admin).
│
├── modules/                   # 🧠 Backend Logic
│   ├── trading_bot.py         # CORE: Main loop, Order execution, State management.
│   ├── server.py              # API: Flask server, Endpoints for Frontend.
│   ├── strategy.py            # LOGIC: Signal generation (RSI/MACD/Bollinger, DCA).
│   ├── indicators.py          # MATH: Technical analysis calculations (ATR, RSI).
│   ├── logger_setup.py        # LOGS: Logging configuration, Audit trail.
│   ├── config.py              # CONFIG: Loads env vars and constants.
│   ├── grid_bot.py            # 🪜 GRID BOT: Separate grid trading strategy.
│   ├── capital_manager.py     # 💰 CAPITAL: Allocation & P&L tracking per bot.
│   └── notifier.py            # 📲 TELEGRAM: Real-time trade notifications.
│
├── botfrontend/               # 💻 Frontend UI (React)
│   └── src/
│       └── components/
│           ├── App.js                 # Main UI Container & Routing.
│           ├── LiveDashboard.js       # Real-time Charts, Metrics, Logs.
│           ├── ControlPanel.js        # Signal Bot controls, DCA toggle.
│           ├── GridBotPanel.js        # 🪜 Grid Bot controls & status.
│           ├── CapitalPanel.js        # 💰 Capital allocation sliders.
│           ├── LogsPage.js            # Log viewer with CSV export.
│           └── BacktestDashboard.js   # Historical simulation interface.
│
├── data/                      # 💾 Persistence
│   ├── bot_state.json         # Signal Bot state (position, metrics).
│   ├── grid_state.json        # Grid Bot state (orders, fills, profit).
│   └── capital_state.json     # Capital allocations & P&L history.
│
└── logs/                      # 📝 Log Storage
    ├── trading_bot.log        # Full debug logs.
    ├── strategy.log           # Strategy tuning logs.
    └── audit.log              # User action audit trail.
```

## 🚀 Feature Map

| Category | Feature | File(s) | Description |
| :--- | :--- | :--- | :--- |
| **Signal Bot** | Live Trading Loop | `trading_bot.py` | Main buy/sell loop with indicators. |
| | Session Restoration | `trading_bot.py` | Atomic DB state saving (SQLAlchemy) for crash recovery. |
| | **MTF Trend Filter** | `strategy.py` | 4H MA50 analysis to avoid buying in bearish macro trends. |
| | **Volume Confirmation**| `strategy.py` | Requires current 15m volume > 1.2x average of last 20. |
| | **Cooldown Period** | `strategy.py` | Prevents "revenge trading" for X mins after a Stop Loss. |
| | **History Pre-fill** | `trading_bot.py` | Instant 200m price load on start to bypass warmup. |
| | Dynamic Auto-Tuning | `trading_bot.py` | Adjusts RSI/SL/Trail based on ATR volatility. |
| | DCA (Sniper Mode) | `strategy.py`, `trading_bot.py` | Dollar-cost averaging on RSI oversold + price drop. |
| **Grid Bot** | Grid Trading | `grid_bot.py` | Limit orders at fixed intervals within a range. |
| | Auto-Range | `grid_bot.py` | ±5% range calculation from current price. |
| | Fee Simulation | `grid_bot.py` | 0.1% fee deducted in test mode for realistic P&L. |
| | State Persistence | `grid_bot.py` | Saves fills/profit to Database. |
| **Capital Manager** | Allocation | `capital_manager.py` | Set % of capital per bot (Signal/Grid). |
| | P&L Tracking | `capital_manager.py` | Tracks profit per bot separately. |
| | Auto-Compound | `capital_manager.py` | Toggle to reinvest profits automatically. |
| | Binance Sync | `capital_manager.py` | Fetch real USDT+ETH balance. |
| **Advanced** | Order Book | `trading_bot.py` | Checks bid/ask depth before buying. |
| | ML Confirmation | `ml_predictor.py` | Predictive signal score (Random Forest). |
| | S/R Awareness | `strategy.py` | Avoids buying at local resistance. |
| **Dashboard** | P&L Thermometer | `ControlPanel.js` | Visual progress bar for session profit. |
| | Rejection Reasons | `server.py` | UI shows exactly why trade was skipped (e.g. "RSI High"). |
| | Settings Compare | `trading_bot.py` | current vs default parameter reporting. |
| **Notifications** | Telegram Alerts | `notifier.py` | Real-time buy/sell/error notifications. |
| | IP Ban Recovery | `server.py` | Auto-restarts once Binance ban lifted time is reached. |
| **Security** | Database (ACID) | `modules/models.py` | SQLAlchemy ORM with SQLite for crash-proof storage. |
| | Logger Rotation | `logger_setup.py` | 5MB x 5 rotation to prevent disk overflow. |
| | Env-based Auth | `config.py`, `server.py` | Admin credentials via environment variables. |
| | CORS Lock | `server.py` | Restricted to `localhost:3000` only. |
| **Logging** | Audit Trail | `logger_setup.py` | Logs all user actions (start/stop/config). |
| | Trade Export | `server.py`, `LogsPage.js` | Download trade history as CSV. |
| **Analytics** | Sharpe Ratio | `trading_bot.py` | Risk-adjusted return calculation. |
| | In-Memory Journal | `trading_bot.py` | Full trade history for Test/Paper sessions. |
| **Frontend** | Capital Panel | `CapitalPanel.js` | Sliders for allocation, **Privacy Toggle**. |
| | Grid Panel | `GridBotPanel.js` | Grid settings, status, reset history, **Manual Sell**. |
| | **Grid Matrix** | `BotStatusHeader.js` | Real-time view of all open buy/sell orders in the grid. |
| | DCA Toggle | `ControlPanel.js` | Enable/disable Defense Mode. |
| **Resilience** | Panic Button | `server.py`, `App.js` | Global emergency shutdown & total liquidation. |
| | Heartbeat Monitor| `server.py`, `notifier.py` | Telegram alerts if bot thread stalls (>5 min). |
| **Phase 3** | TTP (Trailing) | `strategy.py` | Fixed activation and callback percentages. |
| | Recursive DCA | `trading_bot.py` | Geometric scaling for up to 5+ levels. |

---

## 🪜 Grid Bot

Places **limit orders** at fixed price intervals to profit from sideways markets.

### How It Works:
- **Buy orders** below current price
- **Sell orders** above current price  
- When price oscillates, orders fill and re-place on opposite side

### Settings:
| Setting | Description |
|---------|-------------|
| Range | Lower/Upper price bounds (or **Auto-Set** based on volatility) |
| Levels | Number of grid lines (auto-recommended based on volatility) |
| Capital | $ allocated (synced from Capital Panel) |
| Live Mode | Toggle real trading vs simulation |

### Volatility-Based Grid Spacing:
The "Auto-Set Range" button now dynamically adjusts based on market volatility:

| Market Condition | Range | Levels | Why |
|------------------|-------|--------|-----|
| 🟢 Low Volatility (<2%) | ±3% | 15 | Tighter range, more frequent small trades |
| 🟡 Medium Volatility (2-4%) | ±5% | 10 | Balanced settings |
| 🔴 High Volatility (>4%) | ±8% | 8 | Wider range, fewer larger trades |

**🌊 Dynamic Rebalancing:**
- **Auto-Center**: If price exits the grid range by >0.5%, the bot automatically resets and re-centers around the new price.
- **Volatility-Aware**: If "Volatility-Based Spacing" is enabled, it *also* recalculates the optimal range width and level count during this reset.

**⚠️ Capital-Aware Levels:**
The bot automatically caps the number of grid levels to ensure each order is at least **$11** (Binance minimum + buffer).
- *Example*: With $100 capital, max levels = 9 ($100 / $11). Even if Low Volatility recommends 15, it will set 9.
- **Tuning Logs**: All trades are saved to `logs/tuning.csv` with full context (Volatility, Range, Grid Step) for easy analysis in Excel/Sheets.

### Fee Break-Even:
- Grid step must be **>0.2%** to cover Binance fees (0.1% each side)
- Recommended: **0.5%+ step** for comfortable profit

---

## 💰 Capital Manager

Prevents bots from competing for the same funds:
```
Total: $500
├── Signal Bot: 60% = $300
├── Grid Bot:   30% = $150
└── Buffer:     10% = $50
```

### Features:
- **Sliders** to adjust allocation percentage
- **P&L per bot** with win rate stats
- **Auto-Compound toggle** to reinvest profits
- **Sync from Binance** button for real balance

---

## 📲 Telegram Notifications

Get real-time alerts for:
- ✅ **Sniper Trades**: Buy/Sell execution details with **Streak Tracking** (Wins/Losses).
- 🤖 **Grid Trades**: Grid Buy/Profit alerts (Net Profit $)
- 🌊 **Volatility Shifts**: Alerts when market volatility changes >20%
- 📊 **Daily Summary**: Automated 8:00 AM report with P&L, Win Rate, and Trade count.
- ❌ **Errors**: API issues, "Bot Crashed" critical alerts

**Setup**: Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

---

## ⚡ Advanced Engine (New v1.3 Features)

### 📈 Order Book Depth
Before any buy signal is executed, the bot fetches the **Level 2 Order Book**.
- Blocks trade if the **Spread** > 0.5%
- Analyzes Market Depth to minimize slippage.

### 🛡️ Support/Resistance Awareness
The bot identifies local price wall patterns within the last 50 candles.
- **Resistance**: Blocks buy if current price is within 0.5% of a major peak.
- **Support**: Prioritizes dip-buys that occur near recent floor levels.

### 🤖 ML Signal Filtration
**Status:** IMPLEMENTED
Uses a `Random Forest Classifier` to analyze 12+ features of a signal (RSI, Volatility, Volume, MACD) and predicts if it will be a winner. 
- **Self-Correcting**: Retrains on your local `trade_journal.json` every startup.
- **Integrated**: Seamlessly filters buy signals when enabled.

### 📰 Sentiment Analysis
**Status:** IMPLEMENTED
Fetches real-time crypto news and headlines via **CryptoPanic API**. 
- **Analysis**: Uses `TextBlob` (or keyword-matching fallback) to score market sentiment from -1.0 to +1.0.
- **Filter**: Prevents entry if market sentiment is below the user-defined threshold.

---

---

## 📈 Phase 3: Advanced Trading

### 🌊 Trailing Take-Profit (TTP)
Formalized trailing mechanism to capture larger moves:
- **TTP Activation**: Set a profit percentage (e.g., 1.5%) where trailing begins.
- **TTP Callback**: Once active, sell only if price drops by X% (e.g., 0.5%) from the peak.
- **Break-Even Lock**: TTP will not activate unless price is above total round-trip fee costs.

### 🛡️ Recursive DCA Scaling
Enhanced "Defense Mode" for handling major market crashes:
- **Depth**: Configure up to 5+ levels of averaging down.
- **Geometric Sizing**: Position size increases exponentially (e.g., 1.5x) for each deeper level, significantly reducing average entry.
- **Safe Exposure**: Automatically caps DCA amount if quote balance is low.

---

## 🛡️ DCA (Defense Mode)

---

## 🔐 Security

- **Admin credentials** loaded from environment variables (`ADMIN_USER`, `ADMIN_PASS`, `ADMIN_TOKEN`)
- **CORS** restricted to `localhost:3000` only
- **Audit logging** for all user actions
