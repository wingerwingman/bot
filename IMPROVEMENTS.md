# CryptoBot Future Roadmap
Updated: 2026-01-28 (v1.6)

## 🚀 NEW FEATURE IDEAS (Proposed)

### 1. Self-Healing Order Resolution
**Status:** PROPOSED
**Description:** If a Binance order hangs or is partially filled due to API glitches, the bot should automatically re-attempt or adjust.

### 2. Monte Carlo Strategy Stress Testing
**Status:** PROPOSED
**Description:** Run thousands of backtest variations with randomized slippage/delays to find the strategy's true "Edge".

### 3. Multi-Strategy Portfolio Manager
**Suggestion:** Centrally manage risk across multiple symbols and strategies to ensure no single asset exceeds X% of total equity.

### 4. Asymmetric Grid Logic
**Status:** PROPOSED
**Description:** Implement more buy levels below current price and fewer sells above. Ideal for long-term accumulation of an asset.

### 5. Telegram Command Interface
**Status:** PROPOSED
**Description:** Control bots via Telegram commands (e.g., /status, /stop, /sell, /balance) to manage the bot on the go.

### 6. Correlation & Concentration Check
**Status:** PROPOSED
**Description:** Alert the user if Grid + Spot bots are heavily concentrated in the same direction or correlated assets to manage systemic risk.

### 7. Time-of-Day/Session Filter
**Status:** PROPOSED
**Description:** Restrict trading to high-volume/high-liquidity hours (e.g. NY/London overlap) to avoid "chop" in low-volume sessions.

### 8. Absolute Max Position Size
**Status:** PROPOSED
**Description:** Enforce an absolute dollar-value cap on risk per trade (e.g. max $500), regardless of what the dynamic position sizing algorithm calculates.

---

## 🛠️ INFRASTRUCTURE & TUNING

### 5. Automated Database Pruning
**Suggestion:** Automatically archive or delete trade history older than 90 days to keep the SQLite database lightweight and queries fast.

### 6. Dynamic Config Reload & Persistence
**Status:** COMPLETED (v1.6)
**Description:** User overrides for Sentiment, ML, S/R, and other filters now persist across page reloads and server restarts via the centralized BotState database.

### 7. Centralized Performance Profiler
**Suggestion:** Create a dedicated `performance.log` that tracks timing for every major loop iteration (Data Fetch -> Indicator Calc -> Strategy Decision) to pinpoint exact bottlenecks.

---

*This file is for growth suggestions only. Implemented features are documented in FEATURES.md.*
