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
| | Session Restoration | `trading_bot.py` | `load_state()`/`save_state()` for crash recovery. |
| | Dynamic Auto-Tuning | `trading_bot.py` | Adjusts RSI/SL/Trail based on ATR volatility. |
| | DCA (Sniper Mode) | `strategy.py`, `trading_bot.py` | Dollar-cost averaging on RSI oversold + price drop. |
| **Grid Bot** | Grid Trading | `grid_bot.py` | Limit orders at fixed intervals within a range. |
| | Auto-Range | `grid_bot.py` | ±5% range calculation from current price. |
| | Fee Simulation | `grid_bot.py` | 0.1% fee deducted in test mode for realistic P&L. |
| | State Persistence | `grid_bot.py` | Saves fills/profit to `grid_state.json`. |
| **Capital Manager** | Allocation | `capital_manager.py` | Set % of capital per bot (Signal/Grid). |
| | P&L Tracking | `capital_manager.py` | Tracks profit per bot separately. |
| | Auto-Compound | `capital_manager.py` | Toggle to reinvest profits automatically. |
| | Binance Sync | `capital_manager.py` | Fetch real USDT+ETH balance. |
| **Notifications** | Telegram Alerts | `notifier.py` | Real-time buy/sell/error notifications. |
| **Security** | Env-based Auth | `config.py`, `server.py` | Admin credentials via environment variables. |
| | CORS Lock | `server.py` | Restricted to `localhost:3000` only. |
| **Logging** | Audit Trail | `logger_setup.py` | Logs all user actions (start/stop/config). |
| | Trade Export | `server.py`, `LogsPage.js` | Download trade history as CSV. |
| **Frontend** | Capital Panel | `CapitalPanel.js` | Sliders for allocation, P&L display. |
| | Grid Panel | `GridBotPanel.js` | Grid settings, status, reset history. |
| | DCA Toggle | `ControlPanel.js` | Enable/disable Defense Mode. |

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
- ✅ **Sniper Trades**: Buy/Sell execution details
- 🤖 **Grid Trades**: Grid Buy/Profit alerts (Net Profit $)
- 🌊 **Volatility Shifts**: Alerts when market volatility changes >20%
- ❌ **Errors**: API issues, "Bot Crashed" critical alerts

**Setup**: Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

---

## 🛡️ DCA (Defense Mode)

"Sniper" dollar-cost averaging triggers when:
1. RSI < 30 (oversold)
2. Price dropped > 2% from entry

Calculates **Weighted Average Price** for multiple buys.
Max 3 DCA buys per position. Toggle on/off in Control Panel.

---

## 🔐 Security

- **Admin credentials** loaded from environment variables (`ADMIN_USER`, `ADMIN_PASS`, `ADMIN_TOKEN`)
- **CORS** restricted to `localhost:3000` only
- **Audit logging** for all user actions
