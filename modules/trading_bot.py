import os
import time
import threading
import pandas as pd
import datetime
import sys
import json
import requests
import math
from collections import deque
from binance import Client, BinanceAPIException
from pynput import keyboard

# Import new modules using relative imports
from . import config
from . import indicators
from . import logger_setup
from . import notifier
from .strategy import Strategy

class BinanceTradingBot:
    """
    Main Trading Bot Class.
    Manages state, connections, and trade execution.
    """
    KLINE_COLUMNS = [
        "Open time", "Open", "High", "Low", "Close", "Volume", "Close time", "Quote asset volume",
        "Number of trades", "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
    ]

    def __init__(self, 
                 stop_loss_percent=0.01, 
                 sell_percent=0.03, 
                 fixed_stop_loss_percent=0.02, 
                 is_live_trading=False, 
                 volatility_period=14, 
                 filename=None, 
                 trading_fee_percentage=0.001, 
                 slippage=0.001, 
                 quote_asset=None, 
                 base_asset=None, 
                 position_size_percent=0.25,
                 rsi_threshold=40,
                 stop_loss=0.02,
                 trailing_stop=0.03,
                 dynamic_settings=False,
                 resume_state=True,
                 dca_enabled=True,
                 dca_rsi_threshold=30):
        
        self.slippage = slippage
        self.position_size_percent = position_size_percent
        self.dynamic_settings = dynamic_settings
        self.resume_state = resume_state
        self.dca_enabled = dca_enabled
        self.dca_rsi_threshold = dca_rsi_threshold
        self.fear_greed_index = 50 # Default Neutral

        self.is_live_trading = is_live_trading
        self.filename = filename
        
        # Setup Logger via module
        self.logger, self.trade_logger = logger_setup.setup_logger()
        
        self.logger.debug(f"__init__: is_live_trading = {self.is_live_trading}, filename = {self.filename}")
        self.logger.debug(f"Strategy Config: RSI={rsi_threshold}, SL={stop_loss*100}%, Trailing={trailing_stop*100}%")
        
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.client = Client(self.api_key, self.api_secret, tld='us')
        
        # Precision Filters
        self.tick_size = 0.01    # Price/Quote precision (default safe for USDT)
        self.step_size = 0.0001  # Quantity/Base precision (default safe for ETH)
        
        if self.is_live_trading:
            # MOVED: fetch_exchange_filters() down to after self.symbol init
            pass
        
        # Initialize Strategy
        self.strategy = Strategy(
            stop_loss_percent=stop_loss,
            sell_percent=trailing_stop,
            fixed_stop_loss_percent=stop_loss,
            volatility_period=volatility_period,
            rsi_threshold_buy=rsi_threshold,
            trading_fee_percentage=trading_fee_percentage,
            dca_enabled=dca_enabled,
            dca_rsi_threshold=dca_rsi_threshold
        )
        
        # New: Generic balance variables
        self.quote_balance = 0 # e.g. USDT
        self.base_balance = 0  # e.g. ETH
        self.quote_asset = quote_asset or 'USDT' # Default
        self.base_asset = base_asset or 'ETH'   # Default
        
        # Variables for test mode simulation (legacy, or could be unified)
        self.balance_usdt = 0 
        self.eth_bal = 0
        self.btc_bal = 0
        
        if self.is_live_trading:
            # 1. Fetch and Display All Positive Balances (for logging)
            self.logger.debug("Fetching account balances...")
            try:
                account_info = self.client.get_account()
                all_balances = account_info['balances']
                
                # Filter for any asset with positive free OR locked balance
                important_assets = ['USDT', 'USD', 'ETH', 'BTC', 'BNB']
                display_balances = []
                
                for b in all_balances:
                    is_positive = float(b['free']) > 0 or float(b['locked']) > 0
                    is_important = b['asset'] in important_assets
                    
                    if is_positive or is_important:
                        display_balances.append(b)
                
                # Only prompt for input if assets NOT provided via API
                if quote_asset is None or base_asset is None:
                    print("\n------------------------------")
                    print("       CURRENT BALANCES       ")
                    print("------------------------------")
                    if display_balances:
                        print(f"{'Asset':<10} {'Free':<15} {'Locked':<15}")
                        print("-" * 40)
                        for b in display_balances:
                            print(f"{b['asset']:<10} {b['free']:<15} {b['locked']:<15}")
                    print("------------------------------\n")
                    
                    try:
                        q_input = input(f"Enter Quote Asset (Currency to buy with) [default: {self.quote_asset}]: ").strip().upper()
                        if q_input: self.quote_asset = q_input
                        
                        b_input = input(f"Enter Base Asset (Crypto to trade) [default: {self.base_asset}]: ").strip().upper()
                        if b_input: self.base_asset = b_input
                    except KeyboardInterrupt:
                        print("\nUser cancelled operation. Exiting...")
                        sys.exit(0)
                
            except Exception as e:
                self.logger.error(f"Error fetching balances/configuring assets: {e}")
                print(f"Error: {e}")
            
            # 3. Fetch specific balances for declared pair
            self.quote_balance = self.get_balance(self.quote_asset)
            self.base_balance = self.get_balance(self.base_asset)
            
            # Log and Display Configuration
            self.symbol = f"{self.base_asset}{self.quote_asset}"
            msg_pair = f"Trading Pair Configured: {self.symbol}"
            msg_bal = f"Starting Balances: {self.quote_asset}={self.quote_balance}, {self.base_asset}={self.base_balance}"
            
            self.logger.debug(msg_pair)
            self.logger.debug(msg_bal) 
            logger_setup.log_strategy(msg_pair)
            logger_setup.log_strategy(msg_bal)
            print(msg_pair)
            print(msg_bal)
            
            # Shutdown if insufficient funds (Check against minimal threshold)
            if self.quote_balance < 1.0 and self.base_balance < 0.0005:
                # If using something like BTC as quote, < 1.0 is huge.
                # So only apply strict shutdown for known stablecoins or strict zero checks.
                # Modified Check: strict nearly-zero check
                if self.quote_balance <= 0.0001 and self.base_balance <= 0.0001:
                     msg = f"CRITICAL: Insufficient funds ({self.quote_asset} & {self.base_asset} near 0). Shutting down."
                     self.logger.critical(msg)
                     print(msg)
                     sys.exit(0)
                # Warn if low but not zero
                elif self.quote_balance < 10.0 and self.base_balance < 0.001: 
                     print("WARNING: Balances appear low. Ensure you have enough to trade.")

        else:
             self.symbol = 'ETHUSDT' # Test default

        # Now that self.symbol is defined, fetch filters
        if self.is_live_trading:
            self.fetch_exchange_filters()

        self.running = False
        self.bought_price = None
        self.consecutive_stop_losses = 0
        self.consecutive_stop_losses = 0
        self.finished_data = False
        self.dca_count = 0 # Track number of DCA buys
        
        self.last_price = None
        self.last_volatility = None
        self.last_volatility_check_time = None
        self.trading_fee_percentage = trading_fee_percentage # Taker fee
        
        # --- METRICS (Session only) ---
        self.total_trades = 0
        self.winning_trades = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.peak_balance = 0.0 # Will be set on start/resume
        self.max_drawdown = 0.0

        
        if self.is_live_trading:
            # Initial volatility calculation via Helper
            self.last_volatility = self.calculate_volatility()
            self.strategy.set_volatility(self.last_volatility) # Update strategy
            msg_vol = f"__init__: Initial Volatility Calculated: {self.last_volatility}"
            self.logger.debug(msg_vol)
            logger_setup.log_strategy(msg_vol)
            
            # Log Strategy Config (Restored & Moved to Strategy Tab)
            msg_strat = f"Strategy Config: RSI={self.strategy.rsi_threshold_buy}, SL={self.strategy.stop_loss_percent*100}%, Trailing={self.strategy.sell_percent*100}%"
            self.logger.debug(msg_strat)
            logger_setup.log_strategy(msg_strat)
            
            # Load state from previous session (crash recovery)
            if self.resume_state:
                self.load_state()
            else:
                self.logger.debug("Starting FRESH session (Resume disabled).")
                # Forcefully remove the state file to prevent any ghost data loading
                state_file = self.get_state_file_path()
                if os.path.exists(state_file):
                    try:
                        os.remove(state_file)
                        self.logger.debug(f"Deleted previous state file: {state_file}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete state file: {e}")

        self.logger.debug("__init__ completed")

    def sync_time(self):
        """Synchronizes time with the Binance.US server."""
        try:
            server_time = self.client.get_server_time()
            self.client.timestamp_offset = server_time['serverTime'] - int(time.time() * 1000)
            print("Time synchronized with Binance.US server.")
        except Exception as e:
            self.logger.error(f"Error synchronizing time: {e}")

    def log_trade_wrapper(self, action, price, quantity=None, total_value=None, profit=None):
        """Wrapper for the module-level log_trade function."""
        logger_setup.log_trade(self.logger, self.trade_logger, action, price, quantity, total_value, profit)

    def check_trade_log_and_resume(self):
        """Checks the trade log for the last trade and resumes if necessary."""
        try:
            if not os.path.exists(config.TRADE_LOG_FILE):
                return

            with open(config.TRADE_LOG_FILE, 'r') as f:
                lines = f.readlines()

            if not lines:
                return

            last_trade_line = lines[-1].strip()
            parts = last_trade_line.split(',')

            if len(parts) >= 4:
                # Format: Time, Action, Qty, Price,...
                action = parts[1]
                quantity_str = parts[2]
                price_str = parts[3]
                
                try:
                    price = float(price_str)
                    quantity = float(quantity_str)

                    if action == "Buy":
                        if self.bought_price is None:
                            self.bought_price = price
                            self.base_balance = quantity # Resume base balance
                            self.logger.info(f"Resuming from previous buy at: {price}, Quantity: {quantity}")
                            print(f"Resuming trade: Holding {quantity} {self.base_asset} bought at {price}")
                        else:
                            self.logger.warning(f"Trade log indicates a buy, but already holding {self.base_asset}. Not resuming.")

                except ValueError as e:
                    self.logger.error(f"Error parsing trade log for resume: {e}")
            else:
                self.logger.error(f"Invalid trade log format: {last_trade_line}")

        except Exception as e:
            self.logger.exception(f"Error checking trade log: {e}")

    # ================== STATE PERSISTENCE ==================
    
    def get_state_file_path(self):
        """Returns the path to the state file for this trading pair and mode."""
        mode_prefix = 'live' if self.is_live_trading else 'test'
        return os.path.join('data', f'state_{mode_prefix}_{self.symbol}.json')
    
    def save_state(self):
        """Saves bot state to JSON for crash recovery."""
        if not self.is_live_trading:
            return  # Don't save state for backtests
        
        state = {
            'symbol': self.symbol,
            'quote_asset': self.quote_asset,
            'base_asset': self.base_asset,
            'bought_price': self.bought_price,
            'base_balance_at_buy': self.base_balance if self.bought_price else None,
            'position_size_percent': self.position_size_percent,
            'last_update': datetime.datetime.now().isoformat(),
            # Metrics
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'gross_profit': self.gross_profit,
            'gross_loss': self.gross_loss,
            'peak_balance': self.peak_balance,
            'max_drawdown': self.max_drawdown,
            'dca_count': self.dca_count
        }
        
        try:
            os.makedirs('data', exist_ok=True)
            with open(self.get_state_file_path(), 'w') as f:
                json.dump(state, f, indent=2)
            self.logger.info(f"State saved: bought_price={self.bought_price}")
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")
    
    def load_state(self):
        """Loads bot state from JSON on startup."""
        if not self.is_live_trading:
            return  # Don't load state for backtests
        
        state_file = self.get_state_file_path()
        if not os.path.exists(state_file):
            self.logger.debug("No previous state file found. Starting fresh.")
            return
        
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            # Verify it's for the same trading pair
            if state.get('symbol') != self.symbol:
                self.logger.warning(f"State file is for {state.get('symbol')}, not {self.symbol}. Ignoring.")
                return
            
            # Restore position info
            saved_bought_price = state.get('bought_price')
            if saved_bought_price:
                self.bought_price = saved_bought_price
                self.logger.debug(f"Restored position: bought_price={self.bought_price}")
                print(f"🔄 Resuming position: Entry @ ${self.bought_price:.2f}")
            
            # Restore metrics
            self.total_trades = state.get('total_trades', 0)
            self.winning_trades = state.get('winning_trades', 0)
            self.gross_profit = state.get('gross_profit', 0)
            self.gross_loss = state.get('gross_loss', 0)
            self.peak_balance = state.get('peak_balance', 0)
            self.max_drawdown = state.get('max_drawdown', 0)
            self.dca_count = state.get('dca_count', 0)
            
            last_update = state.get('last_update', 'unknown')
            
            # Request: "add loging of what price and other data is loaded when restarting"
            log_msg = (
                f"♻️ SESSION RESTORED from {last_update}\n"
                f"   • Symbol: {self.symbol}\n"
                f"   • Position: {'OPEN @ ' + str(self.bought_price) if self.bought_price else 'NO POSITION'}\n"
                f"   • Metrics: Net Profit ${self.gross_profit - self.gross_loss:.2f} ({self.total_trades} trades)\n"
                f"   • Peak Balance: ${self.peak_balance:.2f} (Max Drawdown: {self.max_drawdown*100:.2f}%)"
            )
            self.logger.debug(log_msg)
            print(log_msg)
            
            # Log to Strategy Tab as well (FULL DETAIL per user request)
            logger_setup.log_strategy(log_msg)
            
            # Force immediate strategy re-check to populate "Strategy Tuning" tab
            self.last_volatility_check_time = None
            
        except Exception as e:
            self.logger.error(f"Error loading state: {e}")
    
    def clear_state(self):
        """Clears the saved state (called after successful position close)."""
        if not self.is_live_trading:
            return
        
        state_file = self.get_state_file_path()
        if os.path.exists(state_file):
            # Don't delete, just update with no position
            self.save_state()
            self.logger.info("State cleared (position closed)")


    def check_price(self):
        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Error: {e}")
            return None
        except (ConnectionError, TimeoutError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            self.logger.warning(f"Network Error (Retrying in 5s): {e}")
            time.sleep(5)
            return None
        except Exception as e:
            error_str = str(e)
            if "Connection aborted" in error_str or "RemoteDisconnected" in error_str:
                self.logger.warning(f"Connection unstable (Retrying in 5s): {e}")
                time.sleep(5)
                return None
            
            self.logger.error(f"An unexpected error occurred: {e}")
            return None

    def get_balance(self, asset):
        try:
            if self.is_live_trading:
                account_info = self.client.get_account()
                for balance in account_info['balances']:
                    if balance['asset'] == asset:
                        return float(balance['free'])
                self.logger.warning(f"{asset} balance not found. Returning 0.0.")
                return 0.0
            else:
                # Test mode simulation
                if asset == self.quote_asset:
                    return self.quote_balance
                elif asset == self.base_asset:
                    return self.base_balance
                elif asset == 'USDT': # Backwards compatibility for hardcoded checks
                     return self.quote_balance
                else:
                    return 0.0
        except Exception as e:
            self.logger.error(f"Error getting {asset} balance: {e}")
            return 0.0

    def calculate_volatility(self):
        """Wrapper calling the pure indicator function."""
        if not self.is_live_trading:
            return 0.5 # Default/Dummy volatility for backtesting to allow start

        try:
            # Need to fetch data first
            klines = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_1DAY, f"{self.strategy.volatility_period} day ago UTC")
            atr = indicators.calculate_volatility_from_klines(klines, self.strategy.volatility_period)
            
            # Normalize to percentage using current price
            current_price = self.check_price()
            if current_price and current_price > 0:
                return atr / current_price
            return None
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None

    def fetch_fear_and_greed(self):
        """Fetches the Fear and Greed Index from alternative.me."""
        try:
            url = "https://api.alternative.me/fng/"
            response = requests.get(url, timeout=5)
            data = response.json()
            if data['data']:
                value = int(data['data'][0]['value'])
                classification = data['data'][0]['value_classification']
                self.logger.debug(f"Fear & Greed Index: {value} ({classification})")
                
                # Also log to Strategy Tab
                logger_setup.log_strategy(f"Fear & Greed Index: {value} ({classification})")
                return value
            return 50 # Neutral default
        except Exception as e:
            self.logger.error(f"Error fetching Fear & Greed Index: {e}")
            return 50

    def fetch_exchange_filters(self):
        """Fetches precision filters (tick_size, step_size) from Binance."""
        try:
            info = self.client.get_symbol_info(self.symbol)
            if info:
                for f in info['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        self.tick_size = float(f['tickSize'])
                    elif f['filterType'] == 'LOT_SIZE':
                        self.step_size = float(f['stepSize'])
                self.logger.debug(f"Exchange Filters Fetched: tick_size={self.tick_size}, step_size={self.step_size}")
        except Exception as e:
            self.logger.error(f"Error fetching exchange filters: {e}")

    def round_step(self, value, step):
        """Rounds value down to the nearest multiple of step."""
        if step == 0: return value
        precision = int(round(-math.log(step, 10), 0))
        return round(int(value / step) * step, precision)

    def calculate_position_size(self, current_price, stop_loss_price):
        """
        Calculates position size based on Risk Parity.
        Risk = Total Account Value * Risk_Per_Trade_Percent
        Position Size = Risk / (Entry - Stop_Loss)
        """
        try:
            # 1. Determine Risk Per Trade (Default 2%)
            risk_percent = 0.02
            
            # Modulate Risk based on Fear & Greed (if enabled)
            if self.dynamic_settings:
                fg_val = getattr(self, 'fear_greed_index', 50)
                if fg_val <= 20:
                    risk_percent = 0.025 # Extreme Fear -> Higher Risk (Buy the dip)
                elif fg_val >= 75:
                    risk_percent = 0.015 # Extreme Greed -> Lower Risk (Protect capital) 

            # Calculate Dollar Risk
            # Use total simulated equity (Base + Quote) or just Quote? 
            # Ideally Total Equity to scale growth.
            total_equity = self.quote_balance + (self.base_balance * current_price) if hasattr(self, 'quote_balance') else self.get_balance(self.quote_asset)
            
            risk_amount = total_equity * risk_percent
            
            # Calculate Distance
            distance_per_unit = abs(current_price - stop_loss_price)
            if distance_per_unit == 0: return 0
            
            # Position Size (Units) = Risk Amount / Loss per Unit
            position_units = risk_amount / distance_per_unit
            
            # Cap at max capital (Can't borrow)
            max_units = (self.quote_balance / current_price) * 0.99 # 99% to cover fees
            
            final_units = min(position_units, max_units)
            
            self.logger.info(f"Dynamic Sizing: Risk ${risk_amount:.2f} (2%), Dist ${distance_per_unit:.2f}, Calc Units {position_units:.4f}, Cap {max_units:.4f}")
            return final_units
            
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            # Fallback to fixed %
            invest_amount = self.get_balance(self.quote_asset) * self.position_size_percent
            return invest_amount / current_price


    def sell_on_ctrl_s(self):
        if self.bought_price is not None and self.base_balance > 0:
            try:
                current_price = self.check_price()
                if current_price is None: return

                profit = ((current_price - self.bought_price) / self.bought_price) * 100

                if self.is_live_trading:
                    self.client.create_order(symbol=self.symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=self.base_balance)
                    self.quote_balance = self.get_balance(self.quote_asset)
                    self.base_balance = self.get_balance(self.base_asset)
                    self.log_trade_wrapper("Ctrl+S Sell", current_price, 0, self.quote_balance, profit)
                else:
                    proceeds = self.base_balance * current_price * (1 - self.trading_fee_percentage)
                    self.quote_balance += proceeds
                    self.log_trade_wrapper("Ctrl+S Sell", current_price, self.base_balance, self.quote_balance, profit)
                    self.base_balance = 0

                self.bought_price = None
                self.shutdown_bot()
                return

            except Exception as e:
                self.logger.error(f"Error placing sell order on Ctrl+Alt+S: {e}")
                return
        else:
            self.logger.info(f"No {self.base_asset} to sell.")
            return

    def shutdown_bot(self):
        self.logger.info("Shutting down the bot...")
        if hasattr(self, 'hotkeys'):
            self.hotkeys.stop()
        self.stop()

    def print_performance_report(self):
        """Prints the current performance report."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        profit_factor = (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else 999.0
        
        print("\n" + "="*40)
        print(f"       SESSION PERFORMANCE REPORT       ")
        print("="*40)
        if self.is_live_trading:
             print(f"Current Quote Bal: {self.quote_balance:.4f} {self.quote_asset}")
             print(f"Current Base Bal:  {self.base_balance:.4f} {self.base_asset}")
        else:
             print(f"Balance:           ${self.quote_balance:.2f}")
             print(f"Max Drawdown:      {self.max_drawdown*100:.2f}%")

        print("-" * 40)
        print(f"Total Trades:      {self.total_trades}")
        print(f"Win Rate:          {win_rate:.1f}% ({self.winning_trades}W / {self.total_trades-self.winning_trades}L)")
        print(f"Profit Factor:     {profit_factor:.2f}")
        print("="*40 + "\n")

    def update_metrics(self, profit_amount, current_equity):
        """Updates internal metrics after a trade close."""
        self.total_trades += 1
        if profit_amount > 0:
            self.winning_trades += 1
            self.gross_profit += profit_amount
        else:
            self.gross_loss += abs(profit_amount)
            
        # Drawdown logic
        if current_equity > self.peak_balance:
            self.peak_balance = current_equity
        
        drawdown = (self.peak_balance - current_equity) / self.peak_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def start(self):
        if not self.running:
            self.running = True
            # Set initial peak balance for metrics
            self.peak_balance = self.get_balance(self.quote_asset) + (self.get_balance(self.base_asset) * (self.check_price() or 0))
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
        else:
            self.logger.warning("Bot is already running.")

    def stop(self):
        self.running = False

    def buy(self, current_price, invest_amount, is_dca=False):
        # Use quote_balance check
        quote_bal = self.get_balance(self.quote_asset)
        
        if quote_bal is None or quote_bal == 0.0:
            self.logger.error(f"Insufficient {self.quote_asset} balance.")
            if self.is_live_trading: self.shutdown_bot()
            return

        if self.bought_price is None:
            try:
                if self.is_live_trading:
                    # Round amount to tick_size (Quote Precision)
                    final_invest_amount = self.round_step(invest_amount, self.tick_size)
                    
                    # Use quoteOrderQty for easy amount specs
                    order = self.client.create_order(symbol=self.symbol, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=final_invest_amount)
                    
                    # Calculate actual average price from fills or cumulative totals
                    cummulative_quote_qty = float(order['cummulativeQuoteQty'])
                    executed_qty = float(order['executedQty'])
                    
                    if executed_qty > 0:
                        if is_dca:
                             # Weighted Average Price Calculation
                             total_cost = (self.base_balance * self.bought_price) + float(order['cummulativeQuoteQty'])
                             total_qty = self.base_balance + executed_qty
                             self.bought_price = total_cost / total_qty
                             
                             # Count DCA
                             self.dca_count += 1
                             self.logger.info(f"DCA #{self.dca_count} Executed. New Avg Price: {self.bought_price:.2f}")
                        else:
                             self.bought_price = cummulative_quote_qty / executed_qty
                             self.dca_count = 0 # Reset on fresh buy
                    else:
                        self.bought_price = float(order['fills'][0]['price']) # Fallback
                    
                    self.quote_balance = self.get_balance(self.quote_asset)
                    self.base_balance = self.get_balance(self.base_asset)
                    
                    total_val = self.quote_balance + (self.base_balance * self.bought_price)
                    
                    self.logger.info(f"Order Filled: Bought {executed_qty} {self.base_asset} @ {self.bought_price:.2f} (Total {cummulative_quote_qty} {self.quote_asset})")
                    notifier.send_telegram_message(f"🟢 <b>BUY EXECUTION</b>\nSymbol: {self.symbol}\nPrice: {self.bought_price:.2f}\nQty: {executed_qty}\nTotal: {cummulative_quote_qty:.2f} {self.quote_asset}")
                    self.log_trade_wrapper("Buy", self.bought_price, executed_qty, total_val)
                    
                    # Save state after buy for crash recovery
                    self.save_state()
                else:
                    quantity = round(invest_amount / current_price * (1 - self.trading_fee_percentage), 8)
                    cost_with_fee = quantity * current_price * (1 + self.trading_fee_percentage)
                    
                    if quote_bal >= cost_with_fee:
                        self.base_balance += quantity
                        self.quote_balance -= cost_with_fee
                        self.bought_price = current_price
                        total_val = self.quote_balance + (self.base_balance * current_price)
                        self.log_trade_wrapper("Buy", current_price, quantity, total_val)
                    else:
                        self.logger.error(f"Test - Buy: Insufficient {self.quote_asset} balance.")
            except Exception as e:
                self.logger.error(f"Error during buy: {e}")

    def sell_position(self, current_price, reason="Sell"):
        """Combined Sell/Stop-Loss Logic"""
        if self.bought_price is not None and self.base_balance > 0:
            try:
                profit = ((current_price - self.bought_price) / self.bought_price) * 100
                profit_amount = 0
                
                if self.is_live_trading:
                     # Round quantity to step_size (Base Precision)
                     qty_to_sell = self.round_step(self.base_balance, self.step_size)
                     
                     # Execute Order
                     order = self.client.create_order(symbol=self.symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=qty_to_sell)
                     
                     # Parse Fill
                     cummulative_quote_qty = float(order['cummulativeQuoteQty']) # Revenue (Gross)
                     executed_qty = float(order['executedQty'])
                     
                     avg_price = cummulative_quote_qty / executed_qty if executed_qty > 0 else float(order['fills'][0]['price'])
                     
                     # Accurate PnL Calculation
                     revenue = cummulative_quote_qty # Approximate (fees might be deducted if paying in quote)
                     cost_basis = executed_qty * self.bought_price
                     profit_amount = revenue - cost_basis
                     real_profit_percent = ((avg_price - self.bought_price) / self.bought_price) * 100
                     
                     # Update State
                     self.quote_balance = self.get_balance(self.quote_asset)
                     self.base_balance = self.get_balance(self.base_asset)
                     
                     self.logger.info(f"Order Filled: Sold {executed_qty} {self.base_asset} @ {avg_price:.2f} (Total {revenue:.2f} {self.quote_asset}, PnL {real_profit_percent:.2f}%)")
                     notifier.send_telegram_message(f"🔴 <b>SELL EXECUTION</b>\nSymbol: {self.symbol}\nPrice: {avg_price:.2f}\nPnL: {real_profit_percent:.2f}%")
                     self.log_trade_wrapper(reason, avg_price, executed_qty, self.quote_balance, real_profit_percent)
                     
                     # Update Metrics Live
                     current_equity = self.quote_balance 
                     self.update_metrics(profit_amount, current_equity)
                     self.print_performance_report()

                else:
                    revenue = self.base_balance * current_price * (1 - self.trading_fee_percentage)
                    profit_amount = revenue - (self.base_balance * self.bought_price)
                    
                    self.quote_balance += revenue
                    self.log_trade_wrapper(reason, current_price, self.base_balance, self.quote_balance, profit)
                    self.base_balance = 0
                    
                    # Update Metrics Test (handled inside test() loop normally, but if called from here)
                    # For consistency, test() loop handles its own logic, but we can unify later.
                    pass
                
                self.bought_price = None
                self.dca_count = 0 # Reset DCA count
                self.strategy.reset_trailing_stop()  # Reset trailing stop tracker
                
                # Save state after sell to clear position (crash recovery)
                if self.is_live_trading:
                    self.save_state()
            except Exception as e:
                self.logger.error(f"Error placing sell order: {e}")

    def run(self):
        self.logger.debug("Starting run method...")
        if self.is_live_trading:
            # Re-check resume logic
            self.check_trade_log_and_resume()
            
            try:
                self.logger.debug("Initializing hotkeys...")
                self.hotkeys = keyboard.GlobalHotKeys({'<ctrl>+<alt>+s': self.sell_on_ctrl_s})
                self.hotkeys.start()
                self.logger.debug("Hotkeys started.")
            except Exception as e:
                self.logger.error(f"Error registering hotkeys: {e}")
                self.logger.warning("Continuing without hotkeys...")
                pass 

        # FREQUENCY UPDATE: Check every 5 minutes (User Preference)
        volatility_check_interval = 5 * 60 
        last_heartbeat_time = time.time()
        
        try:

            self.logger.debug("Entering main trading loop...")
            if self.is_live_trading:
                while self.running:
                    # Heartbeat (every hour)
                    if time.time() - last_heartbeat_time > 3600:
                         last_heartbeat_time = time.time()
                         current_price = self.check_price()
                         
                         if self.bought_price:
                             # HOLDING STATUS
                             profit_pct = ((current_price - self.bought_price) / self.bought_price) * 100
                             peak = self.strategy.peak_price_since_buy or current_price
                             
                             # Calculate Trail Price (Potential Profit Sell)
                             trail_dist = self.strategy.sell_percent
                             trail_price = peak * (1 - trail_dist)
                             
                             # Calculate Break Even
                             sl_price = self.bought_price * (1 - self.strategy.fixed_stop_loss_percent)
                             break_even = self.bought_price * (1 + 2 * self.strategy.trading_fee_percentage)
                             
                             # Determine status
                             if peak > break_even:
                                 trail_profit_pct = ((trail_price - self.bought_price) / self.bought_price) * 100
                                 sell_trigger_msg = f"Trail Stop: {trail_price:.2f} (Profit: {trail_profit_pct:.2f}%)"
                             else:
                                 # Show Shadow Trail even if inactive
                                 dist_to_activate = ((break_even - peak) / peak) * 100
                                 sell_trigger_msg = f"Trail Stop: {trail_price:.2f} (Inactive - Need +{dist_to_activate:.2f}%)"
                                 
                             self.logger.debug(f"Heartbeat - Holding {self.symbol} | Price: {current_price} | PnL: {profit_pct:.2f}% | {sell_trigger_msg} | SL < {sl_price:.2f}")
                             
                         else:
                             # BUY STATUS (RSI Scanner)
                             hb_rsi = indicators.calculate_rsi(self.strategy.price_history) if len(self.strategy.price_history) > 14 else 0
                             target_rsi = self.strategy.rsi_threshold_buy
                             self.logger.debug(f"Heartbeat - Price: {current_price} {self.quote_asset} | RSI: {hb_rsi:.1f} (Buy < {target_rsi})")
                             
                         last_heartbeat_time = time.time()

                    # Volatility Check & Dynamic Auto-Tuning
                    if self.last_volatility_check_time is None or (datetime.datetime.now() - self.last_volatility_check_time).total_seconds() >= volatility_check_interval:
                        old_volatility = self.last_volatility
                        self.last_volatility = self.calculate_volatility()
                        self.strategy.set_volatility(self.last_volatility)
                        
                        # --- VOLATILITY CHANGE ALERT (>20% shift) ---
                        if old_volatility is not None and self.last_volatility is not None:
                            vol_change_pct = abs(self.last_volatility - old_volatility) / old_volatility if old_volatility > 0 else 0
                            if vol_change_pct > 0.20:  # >20% change
                                direction = "↑ INCREASED" if self.last_volatility > old_volatility else "↓ DECREASED"
                                msg = f"🌊 VOLATILITY SHIFT: {direction} {vol_change_pct*100:.0f}% | Was: {old_volatility*100:.2f}% → Now: {self.last_volatility*100:.2f}%"
                                logger_setup.log_strategy(msg)
                                notifier.send_telegram_message(f"<b>{msg}</b>")
                        
                        # --- INDICATOR SNAPSHOT (every volatility check = ~10 min) ---
                        if len(self.strategy.price_history) > 14:
                            snap_rsi = indicators.calculate_rsi(self.strategy.price_history)
                            snap_macd, snap_hist, _ = indicators.calculate_macd(self.strategy.price_history)
                            snap_ma_fast = indicators.calculate_ma(self.strategy.price_history, self.strategy.ma_fast_period)
                            snap_ma_slow = indicators.calculate_ma(self.strategy.price_history, self.strategy.ma_slow_period)
                            snap_price = self.strategy.price_history[-1] if self.strategy.price_history else 0
                            
                            trend = "📈 BULLISH" if snap_ma_fast and snap_ma_slow and snap_ma_fast > snap_ma_slow else "📉 BEARISH"
                            hist_str = f"{snap_hist:+.4f}" if snap_hist else "N/A"
                            rsi_str = f"{snap_rsi:.1f}" if snap_rsi else "N/A"
                            
                            logger_setup.log_strategy(f"📊 SNAPSHOT: Price=${snap_price:.2f} | RSI={rsi_str} | MACD_Hist={hist_str} | Trend={trend} | Vol={self.last_volatility*100:.2f}%")
                        
                        # FETCH SENTIMENT (Fear & Greed)
                        if self.dynamic_settings:
                             self.fear_greed_index = self.fetch_fear_and_greed()
                        
                        # DYNAMIC SETTINGS LOGIC
                        if self.dynamic_settings and self.last_volatility is not None:
                            vol = self.last_volatility
                            vol_percent = vol * 100
                            
                            # FORMULA BASED (Retuned for tighter profit banking)
                            # SL = ~2.0x Vol (was 2.0) - Cap at 6%
                            new_sl_percent = min(6.0, max(1.5, vol_percent * 2.0))
                            
                            # Trail = ~1.5x Vol (was 3.0!) - Tighter to lock profit
                            # Previous 8.2% was too loose, preventing sales on small pumps.
                            new_trail_percent = min(5.0, max(1.0, vol_percent * 1.5))
                            
                            # RSI Logic - Gentler drop for high vol (Allow more trades)
                            new_rsi = 40
                            if vol_percent < 1.0: new_rsi = 45
                            elif vol_percent > 4.0: new_rsi = 30
                            else: new_rsi = int(40 - round((vol_percent - 1.0) * 3.0))
                            new_rsi = max(30, min(50, new_rsi))
                            
                            # --- FEAR & GREED MODIFIER ---
                            fg_msg = ""
                            if self.fear_greed_index is not None:
                                fg_val = self.fear_greed_index
                                if fg_val <= 25:
                                    new_rsi += 5
                                    fg_msg = " (+5 Extreme Fear)"
                                elif fg_val <= 40:
                                    new_rsi += 2
                                    fg_msg = " (+2 Fear)"
                                elif fg_val >= 75:
                                    new_rsi -= 5
                                    fg_msg = " (-5 Extreme Greed)"
                                elif fg_val >= 60:
                                    new_rsi -= 2
                                    fg_msg = " (-2 Greed)"
                                
                                # Clamp final RSI to safe bounds (30-60)
                                new_rsi = max(30, min(60, new_rsi))

                            
                            # Convert back to decimal for Python logic
                            self.strategy.rsi_threshold_buy = new_rsi
                            self.strategy.stop_loss_percent = new_sl_percent / 100.0
                            self.strategy.fixed_stop_loss_percent = new_sl_percent / 100.0
                            # Note: Strategy uses sell_percent as trail distance
                            self.strategy.sell_percent = new_trail_percent / 100.0 
                            
                            current_rsi_val = indicators.calculate_rsi(self.strategy.price_history) if len(self.strategy.price_history) > 14 else 0
                            
                            sell_context = ""
                            if self.bought_price:
                                peak = self.strategy.peak_price_since_buy or self.bought_price
                                new_trail_price = peak * (1 - (new_trail_percent / 100.0))
                                
                                # Also show Profit Activation Price (Break Even) based on fees
                                # Note: Fees don't change with volatility, but good to see context
                                break_even = self.bought_price * (1 + 2 * self.strategy.trading_fee_percentage)
                                sell_context = f" | New Trail Sell: <{new_trail_price:.2f} (Profit Activates > {break_even:.2f})"

                            msg = f"Dynamic Update: Volatility {vol:.2%} -> RSI Target:{new_rsi}{fg_msg} (Current RSI: {current_rsi_val:.1f}), SL:{new_sl_percent:.1f}%, Trail:{new_trail_percent:.1f}%{sell_context}"
                            self.logger.debug(msg) # Hidden from System Log
                            logger_setup.log_strategy(msg) # Visible in Strategy Tab
                        
                        self.last_volatility_check_time = datetime.datetime.now()
                    
                    # --- EXECUTE STRATEGY ---
                    current_price = self.check_price()
                    if current_price is not None:
                         # 1. Update Data
                         self.strategy.update_data(current_price)
                         
                         # 2. Check Signals
                         if self.bought_price is None:
                              # Buy Check
                              if self.strategy.check_buy_signal(current_price, self.last_price):
                                   # Dynamic Position Sizing (Risk Parity)
                                   sl_price = current_price * (1 - self.strategy.fixed_stop_loss_percent)
                                   invest_qty = self.calculate_position_size(current_price, sl_price)
                                   
                                   # Fallback if calc fails or return low
                                   if invest_qty == 0:
                                       invest_qty = (self.get_balance(self.quote_asset) * self.position_size_percent) / current_price
                                   
                                   invest_amount = invest_qty * current_price
                                   self.buy(current_price, invest_amount)
                         else:
                              # DCA Check (Sniper Mode)
                              # DCA Check (Sniper Mode)
                              dca_triggered = False
                              if self.dca_count < config.DCA_MAX_RETRIES:
                                  if self.strategy.check_dca_signal(current_price, self.bought_price):
                                      self.logger.info("🛡️ DCA Signal Detected! Executing Defense Buy...")
                                      notifier.send_telegram_message(f"🛡️ <b>DCA SNIPER ACTIVATED</b>\nSymbol: {self.symbol}\nReason: RSI Oversold & Price Drop")
                                      
                                      # Calculate Buy Size (Use standard logic * Scale Factor)
                                      # Logic: Try to buy 1x Standard Position Size
                                      sl_dummy = current_price * 0.95 # 5% dummy SL for sizing calc
                                      invest_qty = self.calculate_position_size(current_price, sl_dummy)
                                      invest_qty *= config.DCA_SCALE_FACTOR
                                      invest_amount = invest_qty * current_price
                                      
                                      # Check Funds
                                      if self.quote_balance >= invest_amount * 0.99:
                                           self.buy(current_price, invest_amount, is_dca=True)
                                           dca_triggered = True
                                      else:
                                           msg = f"DCA Signal Ignored: Insufficient Funds ({self.quote_balance:.2f} < {invest_amount:.2f})"
                                           self.logger.warning(msg)
                                           logger_setup.log_strategy(msg)

                              if not dca_triggered:
                                  # Sell Checks
                                  action = self.strategy.check_sell_signal(current_price, self.bought_price)
                                  if action == 'SELL' or action == 'STOP_LOSS':
                                   reason = "Sell" if action == 'SELL' else "Stop-loss Sell"
                                   
                                   # --- LOG EXIT CONTEXT (Snapshot) ---
                                   try:
                                        # Calculate Indicators at Exit
                                        rsi_exit = indicators.calculate_rsi(self.strategy.price_history)
                                        macd, hist, signal = indicators.calculate_macd(self.strategy.price_history)
                                        
                                        # Calculate Max Potential
                                        peak = self.strategy.peak_price_since_buy or self.bought_price
                                        max_potential = ((peak - self.bought_price) / self.bought_price) * 100
                                        current_profit = ((current_price - self.bought_price) / self.bought_price) * 100
                                        
                                        log_msg = (f"EXIT SNAPSHOT [{reason}]: PnL {current_profit:.2f}% (Max {max_potential:.2f}%) | "
                                                   f"Indicators: RSI={rsi_exit if rsi_exit else 0:.2f}, MACD_Hist={hist if hist else 0:.4f}")
                                                   
                                        self.logger.info(log_msg)
                                        logger_setup.log_strategy(log_msg)
                                        
                                   except Exception as e:
                                        self.logger.error(f"Error logging exit snapshot: {e}")

                                   self.sell_position(current_price, reason=reason)
                                   
                                   if action == 'STOP_LOSS':
                                       self.consecutive_stop_losses += 1
                                   if self.consecutive_stop_losses >= 3:
                                        self.logger.info("Stopping bot due to 3 consecutive stop losses.")
                                        self.stop()
                                   else:
                                        self.consecutive_stop_losses = 0

                         self.last_price = current_price
                    
                    time.sleep(3)
            else:
                self.test()
                self.running = False
        except Exception as e:
            self.logger.exception(f"An error occurred in run: {e}")
            notifier.send_telegram_message(f"⚠️ <b>CRITICAL ERROR</b>\nBot Crashed: {str(e)}")
            self.stop()
        except KeyboardInterrupt:
            self.shutdown_bot()

    def test(self):
        try:
            historical_data = pd.read_csv(self.filename)
            historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp'])
            
            # --- BACKTEST CONFIGURATION ---
            initial_balance = 1000.0
            self.quote_balance = initial_balance
            self.base_balance = 0
            self.quote_asset = 'USDT'
            
            # Reset Metrics for Test
            self.total_trades = 0
            self.winning_trades = 0
            self.gross_profit = 0.0
            self.gross_loss = 0.0
            self.peak_balance = initial_balance
            self.max_drawdown = 0.0
            
            # Detect Asset from Filename
            fname = os.path.basename(self.filename).lower()
            if 'btc' in fname: self.base_asset = 'BTC'; self.symbol = 'BTCUSDT'
            elif 'sol' in fname: self.base_asset = 'SOL'; self.symbol = 'SOLUSDT'
            elif 'bnb' in fname: self.base_asset = 'BNB'; self.symbol = 'BNBUSDT'
            elif 'xrp' in fname: self.base_asset = 'XRP'; self.symbol = 'XRPUSDT'
            else: self.base_asset = 'ETH'; self.symbol = 'ETHUSDT'
            
            self.last_price = None
            
            # --- METRICS TRACKING ---
            self.total_trades = 0
            self.winning_trades = 0
            self.gross_profit = 0.0
            self.gross_loss = 0.0
            self.peak_balance = initial_balance
            self.max_drawdown = 0.0
            
            # Initial Volatility
            self.last_volatility = self.calculate_volatility()
            if self.is_live_trading:
                 msg_vol = f"__init__: Initial Volatility Calculated: {self.last_volatility}"
                 self.logger.debug(msg_vol) # Hide from System
                 logger_setup.log_strategy(msg_vol) # Show in Strategy
            
            self.strategy.set_volatility(self.last_volatility)
            
            if self.last_volatility is None:
                self.finished_data = True
                return

            print(f"\nSTARTING BACKTEST on {self.filename} ({self.symbol})")
            print(f"Initial Balance: ${initial_balance:.2f}")
            print(f"Fee: {self.trading_fee_percentage*100:.2f}%, Slippage: {self.slippage*100:.2f}%")
            print("-" * 50)
            
            # Dynamic Tuning Helper
            last_tuning_index = 0
            
            for index, row in historical_data.iterrows():
                current_price = row['Price']
                # current_time = row['Timestamp'] # Unused currently
                
                # --- DYNAMIC TUNING (Simulated Periodically) ---
                # Check every 48 periods (Assuming 30m candles -> 24 hours)?
                # Simple check: regenerate settings if index % 48 == 0
                if self.dynamic_settings and index % 48 == 0:
                     # Recalculate Vol (In real backtest, this should be rolling window, but for now use constant or randomized?
                     # Actually, backtest reads static file. Volatility changes over time.
                     # We need meaningful rolling volatility.
                     # But `calculate_volatility` fetches from API (Live). We can't use that here.
                     # We will use the `strategy.current_volatility` if updated?
                     # Strategy updates current_volatility on `update_data`? No, that's price.
                     
                     # Simple approximation: Use current volatility derived from recent prices in `historical_data`?
                     # Too complex to implement rolling ATR from scratch here accurately without large buffer.
                     # Fallback: Just re-apply the logic using the INITIAL volatility (better than nothing) 
                     # OR if possible, calculate rolling ATR if we had the array.
                     
                     # FOR NOW: Re-run the logic block using the stored `self.last_volatility` 
                     # (Assuming static vol for backtest file duration is acceptable for now, 
                     # otherwise we need a full rolling ATR implementation in backtest loop).
                     
                     vol_percent = self.last_volatility * 100
                     
                     # FORMULA BASED (Matches Frontend - Safer)
                     # SL = ~2.0x Vol
                     new_sl_percent = max(1.5, vol_percent * 2.0)
                     # Trail = ~3.0x Vol
                     new_trail_percent = max(2.0, vol_percent * 3.0)
                     # RSI Logic
                     new_rsi = 40
                     if vol_percent < 1.0: new_rsi = 45
                     elif vol_percent > 4.0: new_rsi = 30
                     else: new_rsi = int(40 - round((vol_percent - 1.0) * 3.0))
                     new_rsi = max(30, min(50, new_rsi))
                     
                     self.strategy.rsi_threshold_buy = new_rsi
                     self.strategy.stop_loss_percent = new_sl_percent / 100.0
                     self.strategy.fixed_stop_loss_percent = new_sl_percent / 100.0
                     self.strategy.sell_percent = new_trail_percent / 100.0

                # Update Equity Curve & Drawdown (Mark-to-Market)
                current_equity = self.quote_balance + (self.base_balance * current_price)
                if current_equity > self.peak_balance:
                    self.peak_balance = current_equity
                
                drawdown = (self.peak_balance - current_equity) / self.peak_balance
                if drawdown > self.max_drawdown:
                    self.max_drawdown = drawdown
                
                # --- STRATEGY UPDATE ---
                self.strategy.update_data(current_price)
                
                if self.bought_price is None:
                     if self.strategy.check_buy_signal(current_price, self.last_price):
                          # Dynamic Position Sizing (Risk Parity)
                          sl_price = current_price * (1 - self.strategy.fixed_stop_loss_percent)
                          invest_qty = self.calculate_position_size(current_price, sl_price)
                          
                          # Fallback logic for backtest (Ensure non-zero)
                          if invest_qty <= 0:
                              invest_qty = (self.quote_balance * self.position_size_percent) / current_price
                          
                          invest_amount = invest_qty * current_price
                          
                          if self.quote_balance >= invest_amount * 0.99: # 99% check for rounding
                               # APPLY SLIPPAGE (Buy Higher)
                               execution_price = current_price * (1 + self.slippage)
                               
                               quantity = round(invest_amount / execution_price * (1 - self.trading_fee_percentage), 8)
                               cost = quantity * execution_price
                               
                               self.base_balance += quantity
                               self.quote_balance -= cost
                               self.bought_price = execution_price # Track avg buy price
                               
                               # Log (Simulated)
                               total_val = self.quote_balance + (self.base_balance * current_price)
                               self.log_trade_wrapper("Buy", execution_price, quantity, total_val)
                else:
                     action = self.strategy.check_sell_signal(current_price, self.bought_price)
                     if action in ['SELL', 'STOP_LOSS']:
                          # APPLY SLIPPAGE (Sell Lower)
                          execution_price = current_price * (1 - self.slippage)
                          
                          revenue = self.base_balance * execution_price * (1 - self.trading_fee_percentage)
                          profit_amount = revenue - (self.base_balance * self.bought_price)
                          profit_percent = ((execution_price - self.bought_price) / self.bought_price) * 100
                          
                          self.quote_balance += revenue
                          self.base_balance = 0
                          
                          # Metrics Update via Helper
                          self.update_metrics(profit_amount, self.quote_balance)
                          
                          reason = "Sell" if action == 'SELL' else "Stop-loss Sell"
                          self.log_trade_wrapper(reason, execution_price, 0, self.quote_balance, profit_percent)
                          
                          self.bought_price = None

                self.last_price = current_price

            # --- FINAL REPORT ---
            final_balance = self.quote_balance
            total_return = ((final_balance - initial_balance) / initial_balance) * 100
            
            self.print_performance_report()
            print(f"Final Balance:    ${final_balance:.2f}")
            print(f"Total Return:     {total_return:.2f}%")
            print("="*40 + "\n")
            
            self.logger.info(f"Test Completed. Final: {final_balance}, Trades: {self.total_trades}")
            
            # Store final results for API access (don't reset anymore)
            self.final_balance = final_balance
            self.total_return = total_return
            # Keep quote_balance at final value so dashboard shows correct amount
            # self.quote_balance stays at final_balance
            # self.base_balance stays at 0 (fully liquidated at end)
            self.bought_price = None
            self.finished_data = True

        except Exception as e:
            self.logger.exception(f"Test error: {e}")
            self.finished_data = True
