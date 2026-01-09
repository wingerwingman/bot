import os
import time
import threading
import pandas as pd
import datetime
import sys
from collections import deque
from binance import Client, BinanceAPIException
from pynput import keyboard

# Import new modules using relative imports
from . import config
from . import indicators
from . import logger_setup
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

    def __init__(self, stop_loss_percent=0.01, sell_percent=0.03, fixed_stop_loss_percent=0.02, is_live_trading=False, volatility_period=14, filename=None, trading_fee_percentage=0.01, slippage=0.001, quote_asset=None, base_asset=None):
        self.slippage = slippage # 0.1% default slippage

        self.is_live_trading = is_live_trading
        self.filename = filename
        
        # Setup Logger via module
        self.logger, self.trade_logger = logger_setup.setup_logger()
        
        self.logger.info(f"__init__: is_live_trading = {self.is_live_trading}, filename = {self.filename}")
        
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.client = Client(self.api_key, self.api_secret, tld='us')
        
        # Initialize Strategy
        self.strategy = Strategy(
            stop_loss_percent=stop_loss_percent,
            sell_percent=sell_percent,
            fixed_stop_loss_percent=fixed_stop_loss_percent,
            volatility_period=volatility_period
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
            self.logger.info("Fetching account balances...")
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
            
            self.logger.info(msg_pair)
            self.logger.info(msg_bal)
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

        self.running = False
        self.bought_price = None
        self.consecutive_stop_losses = 0
        self.finished_data = False
        
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
            self.logger.info(f"__init__: Initial Volatility Calculated: {self.last_volatility}")

        self.logger.info("__init__ completed")

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

    def check_price(self):
        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Error: {e}")
            return None
        except (ConnectionError, TimeoutError) as e:
            self.logger.error(f"Network Error: {e}")
            time.sleep(60)
            return None
        except Exception as e:
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
            return indicators.calculate_volatility_from_klines(klines, self.strategy.volatility_period)
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None

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

    def buy(self, current_price, invest_amount):
        # Use quote_balance check
        quote_bal = self.get_balance(self.quote_asset)
        
        if quote_bal is None or quote_bal == 0.0:
            self.logger.error(f"Insufficient {self.quote_asset} balance.")
            if self.is_live_trading: self.shutdown_bot()
            return

        if self.bought_price is None:
            try:
                if self.is_live_trading:
                    # Use quoteOrderQty for easy amount specs
                    order = self.client.create_order(symbol=self.symbol, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=invest_amount)
                    self.bought_price = float(order['fills'][0]['price'])
                    
                    self.quote_balance = self.get_balance(self.quote_asset)
                    self.base_balance = self.get_balance(self.base_asset)
                    
                    total_val = self.quote_balance + (self.base_balance * self.bought_price)
                    self.log_trade_wrapper("Buy", self.bought_price, float(order['origQty']), total_val)
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
                    # Capture exact balance before trade for rough PnL estimate or fetch from order header
                    # For simplicity in Live, we just estimate based on current price
                     revenue = self.base_balance * current_price * (1 - self.trading_fee_percentage) # Est
                     cost_basis = self.base_balance * self.bought_price
                     profit_amount = revenue - cost_basis # Est USD profit
                    
                     self.client.create_order(symbol=self.symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=self.base_balance)
                     self.quote_balance = self.get_balance(self.quote_asset)
                     self.base_balance = self.get_balance(self.base_asset)
                     self.log_trade_wrapper(reason, current_price, 0, self.quote_balance, profit)
                     
                     # Update Metrics Live
                     current_equity = self.quote_balance # Roughly (assuming base is sold)
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
                self.strategy.reset_trailing_stop()  # Reset trailing stop tracker
            except Exception as e:
                self.logger.error(f"Error placing sell order: {e}")

    def run(self):
        self.logger.info("Starting run method...")
        if self.is_live_trading:
            # Re-check resume logic
            self.check_trade_log_and_resume()
            
            try:
                self.logger.info("Initializing hotkeys...")
                self.hotkeys = keyboard.GlobalHotKeys({'<ctrl>+<alt>+s': self.sell_on_ctrl_s})
                self.hotkeys.start()
                self.logger.info("Hotkeys started.")
            except Exception as e:
                self.logger.error(f"Error registering hotkeys: {e}")
                self.logger.warning("Continuing without hotkeys...")
                pass 

        volatility_check_interval = 12 * 60 * 60
        last_heartbeat_time = time.time()
        
        try:
            self.logger.info("Entering main trading loop...")
            if self.is_live_trading:
                while self.running:
                    # Heartbeat
                    if time.time() - last_heartbeat_time > 30:
                         current_price = self.check_price()
                         self.logger.info(f"Heartbeat - Current Price: {current_price} {self.quote_asset}")
                         last_heartbeat_time = time.time()

                    # Volatility Check
                    if self.last_volatility_check_time is None or (datetime.datetime.now() - self.last_volatility_check_time).total_seconds() >= volatility_check_interval:
                        self.last_volatility = self.calculate_volatility()
                        self.strategy.set_volatility(self.last_volatility)
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
                                   invest_amount = self.get_balance(self.quote_asset) * 0.25
                                   self.buy(current_price, invest_amount)
                         else:
                              # Sell Checks
                              action = self.strategy.check_sell_signal(current_price, self.bought_price)
                              if action == 'SELL':
                                   self.sell_position(current_price, reason="Sell")
                              elif action == 'STOP_LOSS':
                                   self.sell_position(current_price, reason="Stop-loss Sell")
                                   self.consecutive_stop_losses += 1
                                   if self.consecutive_stop_losses >= 3:
                                        self.logger.info("Stopping bot due to 3 consecutive stop losses.")
                                        self.stop()
                                   else:
                                        self.consecutive_stop_losses = 0

                         self.last_price = current_price
                    
                    time.sleep(1)
            else:
                self.test()
                self.running = False
        except Exception as e:
            self.logger.exception(f"An error occurred in run: {e}")
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
            self.base_asset = 'ETH'
            self.symbol = 'ETHUSDT'
            
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
            self.strategy.set_volatility(self.last_volatility)
            
            if self.last_volatility is None:
                self.finished_data = True
                return

            print(f"\nSTARTING BACKTEST on {self.filename}")
            print(f"Initial Balance: ${initial_balance:.2f}")
            print(f"Fee: {self.trading_fee_percentage*100:.2f}%, Slippage: {self.slippage*100:.2f}%")
            print("-" * 50)
            
            for index, row in historical_data.iterrows():
                current_price = row['Price']
                # current_time = row['Timestamp'] # Unused currently
                
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
                          invest_amount = self.quote_balance * 0.25 # Invest 25% of available cash
                          if self.quote_balance >= invest_amount:
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
