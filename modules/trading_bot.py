import os
import time
import threading
import pandas as pd
import datetime
from collections import deque
from binance import Client, BinanceAPIException
from pynput import keyboard

# Import new modules using relative imports
from . import config
from . import indicators
from . import logger_setup

class BinanceTradingBot:
    """
    Main Trading Bot Class.
    Manages state, connections, and trade execution.
    """
    KLINE_COLUMNS = [
        "Open time", "Open", "High", "Low", "Close", "Volume", "Close time", "Quote asset volume",
        "Number of trades", "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
    ]

    def __init__(self, stop_loss_percent=0.01, sell_percent=0.03, fixed_stop_loss_percent=0.02, is_live_trading=False, volatility_period=14, filename=None, trading_fee_percentage=0.01):
        self.is_live_trading = is_live_trading
        self.filename = filename
        
        # Setup Logger via module
        self.logger, self.trade_logger = logger_setup.setup_logger()
        
        self.logger.info(f"__init__: is_live_trading = {self.is_live_trading}, filename = {self.filename}")
        
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.client = Client(self.api_key, self.api_secret, tld='us')
        
        self.balance_usdt = 0
        self.eth_bal = 0
        self.btc_bal = 0 
        
        if self.is_live_trading:
            self.balance_usdt = self.get_balance('USDT')
            
        self.running = False
        self.symbol = 'ETHUSDT'
        self.bought_price = None
        
        self.stop_loss_percent = stop_loss_percent
        self.fixed_stop_loss_percent = fixed_stop_loss_percent
        self.sell_percent = sell_percent
        self.consecutive_stop_losses = 0
        self.finished_data = False
        self.volatility_period = volatility_period
        
        self.last_price = None
        self.last_volatility = None
        self.last_volatility_check_time = None
        self.trading_fee_percentage = trading_fee_percentage
        
        self.price_history = deque(maxlen=50) 
        self.ma_fast_period = config.DEFAULT_MA_FAST_PERIOD
        self.ma_slow_period = config.DEFAULT_MA_SLOW_PERIOD
        self.current_volatility = None

        if self.is_live_trading:
            # Initial volatility calculation via Helper
            # Note: We need klines data first to pass to helper.
            # Reuse logic wrapped in method for now, but using new indicator function internally? 
            # Or keep calculate_volatility method as a wrapper? Wrapper is cleaner for now.
            self.last_volatility = self.calculate_volatility()
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

            # Flexible parsing based on number of columns (legacy support + new columns)
            # Standard parts: Timestamp, Action, Quantity, Price, TotalValue(opt), Profit(opt)
            # Minimum required is 4 parts.
            
            if len(parts) >= 4:
                timestamp_str = parts[0]
                action = parts[1]
                quantity_str = parts[2]
                price_str = parts[3]
                
                try:
                    price = float(price_str)
                    quantity = float(quantity_str)

                    if action == "Buy":
                        if self.bought_price is None:
                            self.bought_price = price
                            self.eth_bal = quantity
                            self.logger.info(f"Resuming from previous buy at: {price}, Quantity: {quantity}")
                        else:
                            self.logger.warning("Trade log indicates a buy, but already holding ETH. Not resuming.")

                except ValueError as e:
                    self.logger.error(f"Error parsing trade log line: {last_trade_line}. Error: {e}")
            else:
                self.logger.error(f"Invalid trade log format: {last_trade_line}")

        except Exception as e:
            self.logger.exception(f"An unexpected error occurred checking trade log: {e}")

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
                if asset == 'USDT':
                    return self.balance_usdt
                elif asset == 'ETH':
                    return self.eth_bal
                elif asset == 'BTC':
                    return self.btc_bal
                else:
                    return 0.0
        except Exception as e:
            self.logger.error(f"Error getting {asset} balance: {e}")
            if self.is_live_trading: self.stop()
            return 0.0

    def calculate_volatility(self):
        """Wrapper calling the pure indicator function."""
        try:
            # Need to fetch data first
            klines = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_1DAY, f"{self.volatility_period} day ago UTC")
            return indicators.calculate_volatility_from_klines(klines, self.volatility_period)
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None

    def stop_loss(self, current_price):
        if self.bought_price is not None and self.eth_bal > 0:
            volatility = self.calculate_volatility()
            # Use indicator function
            dynamic_sl_percent = indicators.get_dynamic_stop_loss_percent(volatility, self.stop_loss_percent) if volatility else self.stop_loss_percent
            
            stop_loss_threshold = self.bought_price * (1 - dynamic_sl_percent)

            if current_price < stop_loss_threshold:
                try:
                    if self.is_live_trading:
                        self.client.create_order(
                            symbol=self.symbol,
                            side=Client.SIDE_SELL,
                            type=Client.ORDER_TYPE_MARKET,
                            quantity=self.eth_bal
                        )
                        profit = 0
                        if self.bought_price:
                             profit = ((self.last_price - self.bought_price) / self.bought_price) * 100 # Approx using last_price/current
                        # Log with specific fields
                        # ... (live trading logic logging implies fetching order details which is verbose, keeping simple for refactor)
                        
                        self.balance_usdt = self.get_balance('USDT')
                        self.eth_bal = self.get_balance('ETH')
                        self.log_trade_wrapper("Stop-loss Sell", current_price, 0, self.balance_usdt, profit) # Quantity 0 after sell? Or sold amount?

                    else:
                        profit = ((current_price - self.bought_price) / self.bought_price) * 100
                        self.logger.info(f"Test - Stop loss triggered at {current_price}")
                        proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                        self.balance_usdt += proceeds
                        
                        self.log_trade_wrapper("Stop-loss Sell", current_price, self.eth_bal, self.balance_usdt, profit)
                        self.eth_bal = 0

                    self.bought_price = None
                    self.consecutive_stop_losses += 1
                    if self.consecutive_stop_losses >= 3:
                        self.stop()
                        self.logger.info("Stopping bot due to 3 consecutive stop losses.")
                    return

                except Exception as e:
                    self.logger.error(f"Error placing stop-loss order: {e}")
                    return
            else:
                self.consecutive_stop_losses = 0
                return
        else:
            return

    def sell_on_ctrl_s(self):
        if self.bought_price is not None and self.eth_bal > 0:
            try:
                current_price = self.check_price()
                if current_price is None: return

                profit = ((current_price - self.bought_price) / self.bought_price) * 100

                if self.is_live_trading:
                    self.client.create_order(symbol=self.symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=self.eth_bal)
                    self.balance_usdt = self.get_balance('USDT')
                    self.eth_bal = self.get_balance('ETH')
                    self.log_trade_wrapper("Ctrl+S Sell", current_price, 0, self.balance_usdt, profit)
                else:
                    proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                    self.balance_usdt += proceeds
                    self.log_trade_wrapper("Ctrl+S Sell", current_price, self.eth_bal, self.balance_usdt, profit)
                    self.eth_bal = 0

                self.bought_price = None
                self.shutdown_bot()
                return

            except Exception as e:
                self.logger.error(f"Error placing sell order on Ctrl+Alt+S: {e}")
                return
        else:
            self.logger.info("No ETH to sell.")
            return

    def shutdown_bot(self):
        self.logger.info("Shutting down the bot...")
        if hasattr(self, 'hotkeys'):
            self.hotkeys.stop()
        self.stop()

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
        else:
            self.logger.warning("Bot is already running.")

    def stop(self):
        self.running = False

    def buy(self, current_price, invest_amount):
        usdt_balance = self.get_balance('USDT')
        if usdt_balance is None or usdt_balance == 0.0:
            self.logger.error("Insufficient balance.")
            if self.is_live_trading: self.shutdown_bot()
            return

        if self.bought_price is None:
            try:
                if self.is_live_trading:
                    order = self.client.create_order(symbol=self.symbol, side=Client.SIDE_BUY, type=Client.ORDER_TYPE_MARKET, quoteOrderQty=invest_amount)
                    self.bought_price = float(order['fills'][0]['price'])
                    self.balance_usdt = self.get_balance('USDT')
                    self.eth_bal = self.get_balance('ETH')
                    total_val = self.balance_usdt + (self.eth_bal * self.bought_price)
                    self.log_trade_wrapper("Buy", self.bought_price, float(order['origQty']), total_val)
                else:
                    quantity = round(invest_amount / current_price * (1 - self.trading_fee_percentage), 8)
                    cost_with_fee = quantity * current_price * (1 + self.trading_fee_percentage)
                    if usdt_balance >= cost_with_fee:
                        self.eth_bal += quantity
                        self.balance_usdt -= cost_with_fee
                        self.bought_price = current_price
                        total_val = self.balance_usdt + (self.eth_bal * current_price)
                        self.log_trade_wrapper("Buy", current_price, quantity, total_val)
                    else:
                        self.logger.error(f"Test - Buy: Insufficient USDT balance.")
            except Exception as e:
                self.logger.error(f"Error during buy: {e}")

    def sell(self, current_price):
        if self.bought_price is not None and self.eth_bal > 0:
            try:
                profit = ((current_price - self.bought_price) / self.bought_price) * 100
                if self.is_live_trading:
                    self.client.create_order(symbol=self.symbol, side=Client.SIDE_SELL, type=Client.ORDER_TYPE_MARKET, quantity=self.eth_bal)
                    self.balance_usdt = self.get_balance('USDT')
                    self.eth_bal = self.get_balance('ETH')
                    self.log_trade_wrapper("Sell", current_price, 0, self.balance_usdt, profit)
                else:
                    proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                    self.balance_usdt += proceeds
                    self.log_trade_wrapper("Sell", current_price, self.eth_bal, self.balance_usdt, profit)
                    self.eth_bal = 0
                
                self.bought_price = None
            except Exception as e:
                self.logger.error(f"Error placing sell order: {e}")

    def run(self):
        if self.is_live_trading:
            try:
                self.hotkeys = keyboard.GlobalHotKeys({'<ctrl>+<alt>+s': self.sell_on_ctrl_s})
                self.hotkeys.start()
            except Exception as e:
                self.logger.error(f"Error registering hotkeys: {e}")
                self.running = False
                return

        volatility_check_interval = 12 * 60 * 60
        
        try:
            if self.is_live_trading:
                while self.running:
                    if self.last_volatility_check_time is None or (datetime.datetime.now() - self.last_volatility_check_time).total_seconds() >= volatility_check_interval:
                        self.current_volatility = self.calculate_volatility()
                        self.last_volatility_check_time = datetime.datetime.now()
                        if self.current_volatility is None:
                            continue
                    
                    self.execute_trade_logic()
                    time.sleep(1)
            else:
                self.test()
                self.running = False
        except Exception as e:
            self.logger.exception(f"An error occurred in run: {e}")
            self.stop()

    def test(self):
        try:
            historical_data = pd.read_csv(self.filename)
            historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp'])
            
            self.balance_usdt = 1000
            self.eth_bal = 0
            self.last_price = None
            
            # Initial Volatility
            self.last_volatility = self.calculate_volatility()
            if self.last_volatility is None:
                self.finished_data = True
                return

            historical_data['price_change_percent'] = historical_data['Price'].pct_change()
            historical_data['volatility'] = self.last_volatility # Basic sim: assume constant or recalculate periodically (simplified here)

            bought = False
            
            for index, row in historical_data.iterrows():
                current_price = row['Price']
                current_time = row['Timestamp']
                
                self.logger.info(f"Current time: {current_time}, Current price: {current_price}, Balance: ${self.balance_usdt}, Eth: {self.eth_bal}")

                if self.last_price is not None:
                    price_change_percent = row['price_change_percent']
                    
                    if not bought:
                        if price_change_percent <= -0.01:
                            usdt_balance = self.balance_usdt
                            invest_amount = usdt_balance * 0.25
                            cost_with_fee = invest_amount * (1 + self.trading_fee_percentage) / current_price
                            
                            if usdt_balance >= cost_with_fee:
                                quantity = invest_amount / current_price * (1 - self.trading_fee_percentage)
                                self.balance_usdt -= quantity * current_price * (1 + self.trading_fee_percentage)
                                self.eth_bal += quantity
                                self.bought_price = current_price
                                bought = True
                                
                                total_val = self.balance_usdt + (self.eth_bal * current_price)
                                self.log_trade_wrapper("Buy", current_price, quantity, total_val)
                    else:
                        # Sell Logic
                        if current_price >= self.bought_price * (1 + self.sell_percent):
                            profit = ((current_price - self.bought_price) / self.bought_price) * 100
                            proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                            self.balance_usdt += proceeds
                            self.log_trade_wrapper("Sell", current_price, self.eth_bal, self.balance_usdt, profit)
                            self.eth_bal = 0
                            self.bought_price = None
                            bought = False
                        
                        elif current_price < self.bought_price * (1 - self.fixed_stop_loss_percent):
                            profit = ((current_price - self.bought_price) / self.bought_price) * 100
                            proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                            self.balance_usdt += proceeds
                            self.log_trade_wrapper("Stop-loss Sell", current_price, self.eth_bal, self.balance_usdt, profit)
                            self.eth_bal = 0
                            self.bought_price = None
                            bought = False

                self.last_price = current_price

            self.balance_usdt = 1000
            self.eth_bal = 0
            self.bought_price = None
            self.finished_data = True

        except Exception as e:
            self.logger.exception(f"Test error: {e}")
            self.finished_data = True

    def execute_trade_logic(self):
        try:
            current_price = self.check_price()
            if current_price is None: return

            self.price_history.append(current_price)
            # MA Calculation
            ma_fast = sum(list(self.price_history)[-self.ma_fast_period:]) / self.ma_fast_period if len(self.price_history) > self.ma_fast_period else None
            ma_slow = sum(list(self.price_history)[-self.ma_slow_period:]) / self.ma_slow_period if len(self.price_history) > self.ma_slow_period else None
            
            # RSI
            rsi = indicators.calculate_rsi(self.price_history)

            # Volatility
            self.current_volatility = self.calculate_volatility()
            if self.current_volatility is None: return

            if self.last_price is None:
                self.last_price = current_price
                return

            price_change_percent = (current_price - self.last_price) / self.last_price
            
            if self.bought_price is None:
                if (price_change_percent <= -0.01 and 
                    rsi is not None and rsi < 30 and 
                    ma_fast is not None and ma_slow is not None and ma_fast > ma_slow):
                    
                    invest_amount = self.get_balance('USDT') * 0.25
                    self.buy(current_price, invest_amount)
            
            elif self.bought_price is not None:
                if current_price >= self.bought_price * (1 + self.sell_percent):
                    self.sell(current_price)
                elif current_price < self.bought_price * (1 - self.fixed_stop_loss_percent):
                    self.stop_loss(current_price)

            self.last_price = current_price
            
        except Exception as e:
            self.logger.error(f"Error in trade logic: {e}")
