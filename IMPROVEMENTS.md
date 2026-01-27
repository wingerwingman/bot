# CryptoBot Future Roadmap
Updated: 2026-01-27

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
**Suggestion:** Implement more buy levels below price and fewer sells above. Ideal for long-term accumulation of an asset.

---

## 🛠️ INFRASTRUCTURE & TUNING

### 5. Automated Database Pruning
**Suggestion:** Automatically archive or delete trade history older than 90 days to keep the SQLite database lightweight and queries fast.

### 6. Dynamic Config Reload
**Suggestion:** Allow the bot to reload `config.py` settings (like RSI thresholds) without a full restart, perhaps via a dedicated API endpoint or file watcher.

### 7. Centralized Performance Profiler
**Suggestion:** Create a dedicated `performance.log` that tracks timing for every major loop iteration (Data Fetch -> Indicator Calc -> Strategy Decision) to pinpoint exact bottlenecks.

---

*This file is for growth suggestions only. Implemented features are documented in FEATURES.md.*
