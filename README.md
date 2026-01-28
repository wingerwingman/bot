# 🤖 CryptoBot - Binance.US Trading System (BinanceTradingBot)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://reactjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A powerful, modular trading bot with a **modern React Dashboard**, supporting multiple strategies (**Spot/DCA**, **Grid Trading**) and a **Shared Capital Manager**.

![Dashboard Preview](docs/dashboard-preview.png)

---

## ✨ Key Features

### 📊 Web Dashboard
- **Real-time Monitoring** - Live price charts, RSI, trade history
- **Multi-Bot Support** - Run Spot and Grid bots on different symbols simultaneously
- **Bot Lifecycle** - Create, start, stop, pause, and delete bot instances
- **Logs & Audit Trail** - Strategy decisions, errors, and user actions
- **Backtest Mode** - Test strategies on historical data before going live
- **Advanced Analytics** - Sharpe Ratio, Profit Factor, and P&L Thermometer
- **Missed Trade Log** - Explains why signals were rejected (RSI, Trend, etc.)
- **Paper Trading Mode** - Simulate live trading execution without real funds (zero risk)
- **Instant Readiness** - History pre-fill (200m) on startup eliminates the 3+ hour bot warmup phase
- **Panic Button** - Global emergency shutdown across all bots directly from dashboard
- **Heartbeat Monitoring** - Real-time thread health monitoring with Telegram stalls alerts
- **Performance Reporting** - Automated Weekly, Monthly, and Yearly performance summaries via Telegram
- **Deep Dip Entry** - Strategy bypasses trend filters when RSI < 25 to catch major oversold bounces
- **Smart Dashboard Sorting** - Live bots prioritized at the top; Paper/Testing bots moved to bottom
- **Instant Balance Refresh** - Bypasses cache immediately after trades for 100% accurate balance display


### 🎯 Spot Trading Strategy
| Feature | Description |
|---------|-------------|
| **RSI-Based Entry** | Buys when RSI < 40 (configurable) with trend confirmation |
| **Defense Mode (DCA)** | Recursive scaling (up to 5+ levels) with geometric position sizing |
| **Trailing Take-Profit (TTP)** | Secure profits with trigger thresholds and callback distances |
| **Dynamic Tuning** | Auto-adjusts SL/TP based on real-time volatility (ATR) |
| **Fear & Greed Integration** | Modifies risk based on market sentiment |
| **Multi-Timeframe Analysis** | Checks 4H trend before entry (blocks bearish) |
| **Volume Confirmation** | Requires 1.2x average volume for entries |
| **Stop-Loss Cooldown** | Waits 30 min after stop-loss before re-entry |
| **Slippage Tracking** | Monitors expected vs actual fill prices |
| **Order Book Check** | Verifies depth/spread < 0.5% before entry |
| **S/R Awareness** | Identifies local Support/Resistance levels |
| **ML Signal Filter** | Predicts signal quality using Random Forest |

### 🪜 Grid Trading Bot
| Feature | Description |
|---------|-------------|
| **Range Trading** | Profits from sideways markets with buy-low/sell-high orders |
| **Auto-Range** | Sets bounds based on volatility (ATR) |
| **Manual Sell** | "Sell Now" button to liquidate grid position & cancel orders instantly |
| **Grid Matrix** | Real-time dashboard view of all open buy/sell orders in the grid |
| **Capital-Aware** | Respects minimum order size ($11) and allocated capital |
| **Dynamic Rebalancing** | Auto-centers grid if price exits range |
| **Vol-Based Spacing** | Dynamically adjusting grid width based on market volatility |
| **State Persistence** | Crash-proof design with automatic recovery |

### 💰 Capital Manager
- **Strict Separation** - Spot and Grid bots never compete for funds
- **Privacy Mode** - Toggle to hide sensitive capital/sliders (Streamer friendly)
- **P&L Tracking** - Per-bot profit/loss with win rate stats
- **Auto-Compound** - Optionally reinvest profits
- **Live Sync** - Fetch real balances from Binance

### 📱 Notifications
- **Telegram Alerts** - Trade executions, errors, hourly heartbeats
- **Volatility Shifts** - Alerts when ATR changes >20%
- **Stall Alerts** - Critical notification if a bot process hangs (>5 mins)
- **Daily Summary** - 8:00 AM report with P&L and Streak stats
- **Critical Errors** - Immediate notification if bot crashes

### 🛡️ Security & Logging
- **Log Rotation** - Automatic rotation (Max 25MB) to prevent disk overflow
- **Idempotent Safety** - Race-condition proof logging setup
- **JSON Robustness** - Recursive parsing & NaN sanitation to prevent dashboard data drops
- **Audit Trail** - Tracks every user action (Start, Stop, Config Change)

---

## 🛠️ Installation

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm
- Binance.US Account with API access

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/CryptoBot.git
cd CryptoBot

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate     # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install frontend dependencies
cd botfrontend
npm install --legacy-peer-deps
cd ..

# 5. Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

Create a `.env` file in the project root:

```env
# Binance.US API (required)
BINANCE_US_API_KEY=your_api_key_here
BINANCE_US_API_SECRET=your_api_secret_here

# Telegram Notifications (optional)
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Dashboard Authentication
ADMIN_USER=admin
ADMIN_PASS=your_secure_password
ADMIN_TOKEN=random_secret_token_for_sessions
```

---

## 🚀 Running the Bot

### Start Backend (API Server)
```bash
python main.py
```
The server starts on `http://localhost:5050`

### Start Frontend (in a new terminal)
```bash
cd botfrontend
npm start
```
Opens dashboard at `http://localhost:3000`

### CLI Mode (Advanced)
```bash
python main.py --cli
```
For terminal-based operation without the web UI.

- **Test Mode ('t')**: Run backtest simulation or Paper Trading.
- **Live Trading ('l')**: Run live trading on Binance.US. **Use with caution.**

---

## 📂 Project Structure

```
CryptoBot/
├── main.py                 # Entry point (server or CLI mode)
├── modules/                # Backend logic
│   ├── trading_bot.py      # Spot bot: signals, execution, state
│   ├── grid_bot.py         # Grid bot: range trading
│   ├── strategy.py         # Signal generation (RSI, MACD, MA)
│   ├── indicators.py       # Technical analysis (ATR, RSI, MACD)
│   ├── capital_manager.py  # Fund allocation & P&L tracking
│   ├── server.py           # Flask API endpoints
│   ├── logger_setup.py     # Logging configuration
│   ├── notifier.py         # Telegram integration
│   └── config.py           # Environment & constants
├── botfrontend/            # React dashboard
│   └── src/components/     # UI components
├── data/                   # State persistence & CSV data
├── logs/                   # Application logs
│   ├── trading_us.log      # Detailed operational logs (debug, price, indicators)
│   ├── trades_us.log       # Concise CSV trade history (Buy/Sell, Price, Qty)
│   └── strategy.log        # Strategy decision logs
├── tests/                  # Unit tests
└── docs/                   # Documentation
```

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=modules --cov-report=html
```

---

## 📖 Documentation

- [FEATURES.md](FEATURES.md) - Detailed feature documentation
- [IMPROVEMENTS.md](IMPROVEMENTS.md) - Planned enhancements
- [FIXES.md](FIXES.md) - Recent bug fixes

---

## 🔒 Security Notes

- **Never commit `.env`** - Contains API secrets
- **API Keys** - Use read-only keys when possible; enable trading only for trusted setups
- **CORS** - Backend only accepts requests from `localhost:3000`
- **Authentication** - Dashboard requires login; sessions expire

---

## ⚠️ Disclaimer

**USE AT YOUR OWN RISK.** This software is for educational purposes. Cryptocurrency trading involves substantial risk of loss. The developers are not responsible for any financial losses incurred while using this bot.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

*Last updated: 2026-01-28* (v1.6 - Performance Reports & "Deep Dip" Strategy Update)
