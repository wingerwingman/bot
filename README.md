# 🤖 Crypto Trading Bot (Binance.US)

A powerful, modular trading bot with a **modern Web Dashboard**, supporting multiple strategies (**Sniper/DCA**, **Grid Trading**) and a **Shared Capital Manager**.

## ✨ Key Features

### 1. 📊 Web Dashboard
- **React-based UI** for real-time monitoring and control.
- **Multi-Bot Support**: Run multiple Spot and Grid bots on different symbols simultaneously.
- **Bot Lifecycle**: Create, start, stop, and permanently **delete** bot instances.
- **Charts**: Live price charting with indicators (RSI, Bollinger Bands).
- **Logs**: Real-time strategy decision logs and error tracking.
- **Controls**: Start/Stop bots, adjust settings on the fly.

### 2. 🛡️ Sniper Strategy (DCA)
- **RSI-Based Entry**: Buys when oversold (RSI < 30-40) and volatility is favorable.
- **Defense Mode (DCA)**: If price drops after entry, buys more at lower levels (`config.DCA_MAX_RETRIES`).
  - Detailed Strategy Logging: Shows exact RSI values and price drops when triggered.
- **Dynamic Exit**: Uses trailing stops and take-profit targets tailored to volatility.

### 3. 🕸️ Grid Trading Bot
- **Range Trading**: Profits from sideways markets by buying low and selling high within a range.
- **Auto-Range**: Automatically sets grid bounds and levels based on **Market Volatility (ATR)**.
  - *Low Vol*: Tighter range, more levels.
  - *High Vol*: Wider range, fewer levels.
- **Dynamic Capital Limit**: Respects allocated capital slider + automatically **reinvests Net Profits** for compounding growth.
- **Pause & Resume**: Stopping the bot moves it to "Pause" state (keeping orders active). Resuming picks up exactly where it left off.
- **Robust Persistence**: State is saved after every trade. Crash-proof design ensures no data loss.
- **Smart Partitioning**: 
  - **Grid Awareness**: Spot Bot is aware of Grid Bot's locked funds and will not sell them.
  - **Grid Reservation**: Grid Bot respects Spot Bot's holdings and starts empty if funds are occupied.

### 4. 💰 Capital Manager & Partitioning
- **Strict Separation**: Spot Strategies and Grid Strategies run on the same account but **never** can touch each other's funds.
- **P&L Tracking**: Tracks wins/losses and auto-compounds profits per bot.
- **Live Sync**: "Sync" button on dashboard instantly refreshes all balances from Binance.

### 5. 📱 Notifications
- **Smart Alerts**:
  - ✅ **Sniper Trades**: Buy/Sell execution details.
  - 🤖 **Grid Trades**: Real-time Grid Buy and Net Profit alerts.
  - 🌊 **Volatility Shifts**: Alerts when market volatility changes >20%.
  - ❌ **Critical Errors**: Immediate alert if the bot crashes.
- **Status Updates**: Periodic heartbeat messages (every hour).

---

## 🛠️ Setup & Usage

### Prerequisites
- Python 3.10+
- Node.js & NPM
- Binance.US Account (API Key & Secret)

### Installation
1. **Clone & Install Python Deps**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Install Frontend Deps**:
   ```bash
   cd botfrontend
   npm install --legacy-peer-deps
   ```
3. **Environment**:
   Create `.env` file:
   ```
   API_KEY=your_key
   API_SECRET=your_secret
   TELEGRAM_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_id
   ADMIN_USER=admin
   ADMIN_PASS=pass
   ADMIN_TOKEN=secret_token
   ```

### Running
1. **Start Backend**:
   ```bash
   python main.py
   ```
2. **Start Frontend (in new terminal)**:
   ```bash
   cd botfrontend
   npm start
   ```
3. **Open Dashboard**:
   http://localhost:3000

---

## 🧪 Testing
Run the full unit test suite:
```bash
python -m pytest tests/ -v
```

## 📂 Project Structure
- `modules/`: Core logic (Strategy, GridBot, CapitalManager).
- `botfrontend/`: React dashboard source.
- `data/`: Persistence files (grid_state.json, capital_state.json).
- `logs/`: Application logs.

---
*Disclaimer: Use at your own risk. Crypto markets are highly volatile.*
