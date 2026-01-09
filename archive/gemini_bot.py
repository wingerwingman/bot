import os
import time
import logging
import threading
import pandas as pd
import pandas_ta as ta  # Import for RSI calculation (install with: pip install pandas_ta)
from collections import deque # Needed for live trading calculations.
from binance import Client, BinanceAPIException  # Import BinanceAPIException
from dotenv import load_dotenv
import datetime
import signal
import numpy
npNaN = numpy.nan
from pynput import keyboard

load_dotenv()

class BinanceTradingBot:
    KLINE_COLUMNS = [
        "Open time", "Open", "High", "Low", "Close", "Volume", "Close time", "Quote asset volume",
        "Number of trades", "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
    ]

    def __init__(self, stop_loss_percent=0.01, sell_percent=0.03, fixed_stop_loss_percent=0.02, is_live_trading=False, volatility_period=14, filename=None, trading_fee_percentage=0.01):
        self.is_live_trading = is_live_trading
        self.filename = filename
        self.logger = self.setup_logger()
        self.logger.info(f"__init__: is_live_trading = {self.is_live_trading}, filename = {self.filename}")
        self.api_key = os.getenv('BINANCE_US_API_KEY')
        self.api_secret = os.getenv('BINANCE_US_API_SECRET')
        self.client = Client(self.api_key, self.api_secret, tld='us')
        self.balance_usdt = 0
        self.eth_bal = 0
        self.btc_bal = 0 # Initialize btc_bal to prevent AttributeError
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
        self.trading_fee_percentage = trading_fee_percentage  # Store as attribute
        self.price_history = deque(maxlen=50) # Set maxlen to prevent memory leak
        self.ma_fast_period = 5  # Example value; adjust as needed
        self.ma_slow_period = 20 # Example value; adjust as needed
        self.current_volatility = None # Initialize to none.
        if self.is_live_trading:  # Only calculate initial volatility for live trading
            self.last_volatility = self.calculate_volatility()
            self.logger.info(f"__init__: Initial Volatility Calculated: {self.last_volatility}") # Log after calculation

        self.logger.info("__init__ completed") # Mark completion




    def sync_time(self):
        """Synchronizes time with the Binance.US server."""
        try:
            server_time = self.client.get_server_time()
            self.client.timestamp_offset = server_time['serverTime'] - int(time.time() * 1000)
            print("Time synchronized with Binance.US server.")
            self.time_synced.set()
        except Exception as e:
            self.logger.error(f"Error synchronizing time: {e}")

    def setup_logger(self):
        logger = logging.getLogger("BinanceTradingBot")
        logger.setLevel(logging.DEBUG)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        fh = logging.FileHandler('trading_us.log')  # Main log file
        fh.setLevel(logging.DEBUG) # Log everything from DEBUG and above in main file.

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        ch.setFormatter(formatter)
        fh.setFormatter(formatter)

        logger.addHandler(ch)
        logger.addHandler(fh)

        # Create a separate logger specifically for trade logging:
        self.trade_logger = logging.getLogger("trade_logger") # Different logger name
        self.trade_logger.setLevel(logging.INFO)
        self.trade_logger.propagate = False # Prevent propagation to root logger
        
        # Check if handler already exists to prevent duplicates
        if not self.trade_logger.handlers:
            # CLEAR files on startup (w mode)
            if os.path.exists('trades_us.log'):
                open('trades_us.log', 'w').close()
            if os.path.exists('trading_us.log'):
                open('trading_us.log', 'w').close()

            trade_fh = logging.FileHandler('trades_us.log')  # Trade log file
            trade_fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s')) # Use CSV format
            self.trade_logger.addHandler(trade_fh)

        return logger # Return the MAIN logger.


    def log_trade(self, action, price, quantity=None, total_value=None, profit=None):
        """Logs trade details to the trade log file using the logger."""
        try:
             # Logger is configured to add timestamp and format as csv: %(asctime)s,%(message)s
             msg_parts = [str(action), str(quantity), str(price)]
             if total_value is not None:
                 msg_parts.append(str(total_value))
             if profit is not None:
                 msg_parts.append(f"{profit:.2f}%")
                 
             msg = ",".join(msg_parts)
                 
             self.logger.info(f"DEBUG: Attempting to log trade: {msg}") # Log to main log
             self.trade_logger.info(msg)
             
             # Force flush all handlers
             for handler in self.trade_logger.handlers:
                 handler.flush()
                 
        except Exception as e:
            self.logger.error(f"Error logging trade: {e}")


    def check_trade_log_and_resume(self):
        """Checks the trade log for the last trade and resumes if necessary."""
        self.trade_log_file = 'trades_us.log'  # Define the trade log filename

        try:
            if not os.path.exists(self.trade_log_file):
                return  # Log file doesn't exist, nothing to resume

            with open(self.trade_log_file, 'r') as f:
                lines = f.readlines()  # Read all lines

            if not lines:
                return  # Log file is empty, nothing to resume

            last_trade_line = lines[-1].strip()  # Get the last non-empty line
            parts = last_trade_line.split(',') # Split using comma.

            if len(parts) == 4: # Correct number of parts for trade resumption
                timestamp_str, action, quantity_str, price_str = parts
                
                try:
                    timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    quantity = float(quantity_str)
                    price = float(price_str)

                    if action == "Buy":
                        if self.bought_price is None:  # Only resume if not already holding
                            self.bought_price = price
                            self.eth_bal = quantity # Correctly set quantity bought based on logs.
                            self.logger.info(f"Resuming from previous buy at: {price}, Quantity: {quantity}")
                        else:
                            self.logger.warning("Trade log indicates a buy, but already holding ETH. Not resuming.")
                            # This would be very unusual; check your logs, and consider reconciling balances with Binance

                    # No resume logic for sell in this log format, as after a sell, the bot should be in its initial state.

                except ValueError as e:
                    self.logger.error(f"Error parsing trade log line: {last_trade_line}. Error: {e}")

            else:
                self.logger.error(f"Invalid trade log format (incorrect number of values): {last_trade_line}")


        except Exception as e:
            self.logger.exception(f"An unexpected error occurred checking trade log: {e}")

    def on_press(self, key):  # Add this method
        """Handles key presses (currently does nothing)."""
        try:  # Attempt to convert key to character
            char = key.char
        except AttributeError: # Log more info if failed.
            self.logger.debug(f"Special key {key} pressed")

        else: # Log the letter that was pressed.
            self.logger.debug(f"Alphanumeric key {char} pressed")
        

    def on_release(self, key):  # Add this method
        """Handles key releases (currently does nothing)."""
        pass # This does nothing for now, but is needed to prevent errors.
    
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
        """Retrieves the current balance of a specified asset from Binance.US or simulates it in test mode."""
        try:
            if self.is_live_trading:
                account_info = self.client.get_account()
                for balance in account_info['balances']:
                    if balance['asset'] == asset:
                        return float(balance['free'])
                self.logger.warning(f"{asset} balance not found in account info. Returning 0.0.")
                return 0.0  # Return 0.0 if asset not found
            else:
                # Simulate balance in test mode (no API call)
                if asset == 'USDT':
                    return self.balance_usdt
                elif asset == 'ETH':
                    return self.eth_bal
                elif asset == 'BTC':
                    return self.btc_bal # Assuming btc_bal attribute is initialized
                else:
                    self.logger.warning(f"Test mode: Balance for {asset} not simulated. Returning 0.0.")  # Better to be explicit about the behavior
                    return 0.0
        except BinanceAPIException as e:
            self.logger.error(f"Binance API error getting {asset} balance: {e}")
            if self.is_live_trading:
                self.stop()
            return 0.0
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred getting {asset} balance: {e}")
            if self.is_live_trading:
                self.stop()
            return 0.0

    def manage_csv_file(self, filename, data):
        """Manages CSV file creation/updates."""
        max_file_size = 10 * 1024 * 1024  # 10MB
        try:
            if os.path.exists(filename) and os.path.getsize(filename) > max_file_size:
                now = datetime.datetime.now()
                rotated_filename = f"{filename}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
                os.rename(filename, rotated_filename)
                self.logger.info(f"Rotated CSV file to: {rotated_filename}")

            data.to_csv(filename, mode='a', header=not os.path.exists(filename), index=False)
        except OSError as e:
            self.logger.error(f"Error managing CSV file: {e}")


    def get_historical_data(self, symbol, interval, start_str, end_str=None):
        """Retrieves historical kline data with robust error handling and pagination."""
        try:
            klines = self.client.get_historical_klines(symbol, interval, start_str, end_str)
            df = pd.DataFrame(klines, columns=self.KLINE_COLUMNS)
            
            # Convert numeric columns
            numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
            df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
            
            # Convert timestamp
            df['Timestamp'] = pd.to_datetime(df['Open time'], unit='ms')
            
            # Keep only necessary columns and rename Close to Price for consistency
            df = df[['Timestamp', 'Close']]
            df.rename(columns={'Close': 'Price'}, inplace=True)
            
            return df

        except Exception as e:
            self.logger.error(f"An unexpected error occurred in get_historical_data: {e}")
            return None


    def run(self):  # Improved run method
        """Main loop for trading (test or live)."""
        if self.is_live_trading:
            try:
                self.hotkeys = keyboard.GlobalHotKeys({'<ctrl>+<alt>+s': self.sell_on_ctrl_s})  # Correct syntax
                self.hotkeys.start()
            except Exception as e:  # Handle any exceptions during hotkey registration
                self.logger.error(f"Error registering hotkeys using pynput: {e}")
                self.running = False  # Stop the bot if hotkey registration fails
                return  

        volatility_check_interval = 12 * 60 * 60  # 12 hour in seconds
        self.last_volatility_check_time = None  # Initialize time of last check

        try:

            if self.is_live_trading: # Do this BEFORE the loop
                while self.running: # Live trading loop
                    if self.last_volatility_check_time is None or (datetime.datetime.now() - self.last_volatility_check_time).total_seconds() >= volatility_check_interval:
                        self.current_volatility = self.calculate_volatility()  # Recalculate volatility only once per interval
                        self.last_volatility_check_time = datetime.datetime.now()  # Update last check time
                        if self.current_volatility is None:  # Handle potential error
                            self.logger.error("Error calculating volatility. Cannot trade.")
                            continue  # Skip to the next iteration if volatility calculation fails

                    self.execute_trade_logic()  # Execute trading logic (uses self.current_volatility)
                    time.sleep(1)

            else:
                self.test()  # Run backtesting ONCE outside loop
                self.running = False # Stop after backtest.


        except Exception as e:
            self.logger.exception(f"An error occurred in run: {e}")  # Log full exception details
            self.stop()

    def test(self):
        """Simulates trading using historical data."""
        try:
            historical_data = pd.read_csv(self.filename)
            historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp'])  # Convert to datetime objects

            self.balance_usdt = 1000  # Initial USDT balance for backtesting
            self.eth_bal = 0        # Initial ETH balance
            self.last_price = None
            volatility_check_interval = 12 * 60 * 60  # 12 hours in seconds
            self.last_volatility_check_time = None
            self.last_volatility = self.calculate_volatility() # Get initial volatility.


            if self.last_volatility is None:  # Handle potential error in volatility calculation
                self.logger.error("Error calculating initial volatility. Exiting backtest.")
                self.finished_data = True
                return

            historical_data['price_change_percent'] = historical_data['Price'].pct_change() # precalculate for speed.
            historical_data['volatility'] = self.last_volatility # Store starting volatility

            trades = []  # List to store trade details
            bought = False
            buy_price = 0
            sell_price = 0
            trade_count = 0

            for index, row in historical_data.iterrows(): # Iterate through historical data
                current_price = row['Price']
                current_time = row['Timestamp']

                # Periodic Volatility Check
                if self.last_volatility_check_time is None or (current_time - self.last_volatility_check_time).total_seconds() >= volatility_check_interval:
                    new_volatility = self.calculate_volatility() # Recalculate
                    self.last_volatility_check_time = current_time
                    if new_volatility is not None: # Update the current volatility and dataset.
                        self.last_volatility = new_volatility
                        historical_data.loc[index:, 'volatility'] = new_volatility # update volatility for all remaining rows.
                    else:
                        self.logger.error("Error calculating volatility during backtest. Keeping current value.")


                volatility = row['volatility']  # Use current or updated volatility


                self.logger.info(f"Current time: {current_time}, Current price: {current_price}, Volatility: {volatility}, "
                                 f"Balance: ${self.balance_usdt}, Eth: {self.eth_bal}")

                if self.last_price is not None: # Need last price to calculate price change
                    price_change_percent = row['price_change_percent']

                    if not bought:  # Buy Logic
                        if price_change_percent <= -0.01: # Reverted to original logic
                            usdt_balance = self.balance_usdt
                            invest_percentage = 0.25
                            invest_amount = usdt_balance * invest_percentage
                            cost_with_fee = invest_amount * (1 + self.trading_fee_percentage) / current_price # Needed amount with fee

                            if usdt_balance >= cost_with_fee:
                                quantity = invest_amount / current_price * (1 - self.trading_fee_percentage) # How much to buy after fee
                                self.balance_usdt -= quantity * current_price * (1 + self.trading_fee_percentage) # Subtract cost with fee.
                                self.eth_bal += quantity  # Add amount we bought.

                                self.bought_price = current_price
                                bought = True
                                buy_price = current_price
                                buy_time = current_time
                                self.logger.info(f"Test - Simulated Buy: {quantity} ETH at {current_price}")
                                self.log_trade("Buy", current_price, quantity, self.balance_usdt + (quantity * current_price)) # Log total value (USDT + ETH value)
                                trade = {  # Store trade data
                                    "buy_time": buy_time,
                                    "buy_price": buy_price,
                                    "type": "buy"
                                }
                                trades.append(trade)

                            else:
                                self.logger.debug(f"Test - Buy: Insufficient USDT balance. Available: {usdt_balance}, Needed: {cost_with_fee}, "
                                                  f"current_price: {current_price}")

                    else:  # Sell and Stop-loss Logic
                        if current_price >= self.bought_price * (1 + self.sell_percent): # Sell Condition
                            proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage) # Get amount made after fees
                            self.balance_usdt += proceeds # Add to balance
                            sell_price = current_price
                            self.eth_bal = 0
                            self.bought_price = None
                            bought = False
                            trade_count += 1

                            self.logger.info(f"Test - Simulated Sell: {self.eth_bal} ETH at {current_price}")
                            profit = ((sell_price - buy_price) / buy_price) * 100 # calculate profit percentage
                            self.log_trade("Sell", current_price, self.eth_bal, self.balance_usdt, profit) # Log total value and profit

                            self.logger.info(f"Test - Trade {trade_count} complete, Profit: {profit:.2f}%")

                            trade = {
                                "sell_time": current_time,
                                "sell_price": current_price,
                                "profit_percent": profit,
                                "type": "sell"
                            }
                            trades.append(trade)


                        elif current_price < self.bought_price * (1 - self.fixed_stop_loss_percent): # Stop loss condition
                            # Stop-loss triggered
                            proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage) # Proceeds after fee
                            self.balance_usdt += proceeds # Add to balance
                            sell_price = current_price
                            self.eth_bal = 0
                            self.bought_price = None
                            bought = False
                            trade_count += 1

                            self.logger.info(f"Test - Simulated Stop-loss Sell: {self.eth_bal} ETH at {current_price}")
                            profit = ((sell_price - buy_price) / buy_price) * 100
                            self.log_trade("Stop-loss Sell", current_price, self.eth_bal, self.balance_usdt, profit) # Log total value and profit

                            self.logger.info(f"Test - Trade {trade_count} complete, Profit: {profit:.2f}%")

                            trade = {
                                "sell_time": current_time,
                                "sell_price": current_price,
                                "profit_percent": profit,
                                "type": "stop_loss"
                            }
                            trades.append(trade)

                self.last_price = current_price

            # KPI Calculation (After the loop):
            # ... (Existing KPI calculation and logging from your original code)

            self.balance_usdt = 1000  # Reset balances after backtest
            self.eth_bal = 0
            self.bought_price = None
            self.finished_data = True  # Signal backtest completion

        except FileNotFoundError:
            self.logger.error(f"Error: CSV file '{self.filename}' not found. Exiting backtest.")
            self.finished_data = True
            return # Make sure to exit here.
        except ValueError as e: # Catch bad data errors
            self.logger.error(str(e))
            self.finished_data = True
            return
        except Exception as e:  # Catch any other unexpected errors
            self.logger.exception(f"An unexpected error occurred in test: {e}")
            self.finished_data = True
            return

    def calculate_rsi(self, price_series, length=14):
        """Calculates RSI for a given price series."""
        try:
            if len(price_series) < length:  # Not enough data for RSI calculation yet
                return None

            # Convert deque to Series for pandas_ta
            close_series = pd.Series(price_series)
            rsi_indicator = ta.rsi(close_series, length=length)
            return rsi_indicator.iloc[-1] # Return the latest RSI value

        except Exception as e:
            self.logger.error(f"Error calculating RSI: {e}")
            return None
    
    def execute_trade_logic(self):
        """Core trading logic incorporating MA and RSI, with proper error handling."""
        try:
            current_price = self.check_price()
            if current_price is None:
                self.logger.error("Error retrieving price. Skipping this iteration.")
                time.sleep(60)  # Wait before retrying
                return

            # 1. Moving Average Calculation (Live Trading Adaptation):
            self.price_history.append(current_price)
            ma_fast = None  # Initialize ma_fast and ma_slow inside loop
            ma_slow = None
            if len(self.price_history) > self.ma_fast_period:
                ma_fast = sum(list(self.price_history)[-self.ma_fast_period:]) / self.ma_fast_period
            if len(self.price_history) > self.ma_slow_period:
                ma_slow = sum(list(self.price_history)[-self.ma_slow_period:]) / self.ma_slow_period


            # 2. RSI Calculation (Live Trading Placeholder - YOU MUST IMPLEMENT):
            rsi = None
            if self.is_live_trading:
                rsi = self.calculate_rsi(self.price_history)  # Implement this function!

            # Volatility is needed even before buy. Calculate here:
            self.current_volatility = self.calculate_volatility() 
            if self.current_volatility is None:
                self.logger.error("Error calculating volatility. Cannot trade.")
                return

            if self.last_price is None: # Set last price.
                self.last_price = current_price
                return

            price_change_percent = (current_price - self.last_price) / self.last_price

            usdt_balance = self.get_balance('USDT')
            # Handle insufficient balance here to avoid redundancy
            if usdt_balance is None or usdt_balance == 0:
                self.logger.error("Error getting USDT balance or balance is zero. Cannot trade.")
                if self.is_live_trading:
                    self.stop()  # Shutdown in live trading
                return


            if self.bought_price is None:  # Buy logic
                # Buy conditions (RSI, MA, Price change):
                if (
                    price_change_percent <= -0.01 and
                    rsi is not None and rsi < 30 and         # Check RSI
                    ma_fast is not None and ma_slow is not None and ma_fast > ma_slow  # Check MAs
                ):
                    invest_percentage = 0.25
                    invest_amount = usdt_balance * invest_percentage
                    self.buy(current_price, invest_amount)


            elif self.bought_price is not None:  # Sell and Stop-loss logic
                if current_price >= self.bought_price * (1 + self.sell_percent):  # Sell
                    self.sell(current_price)
                elif current_price < self.bought_price * (1 - self.fixed_stop_loss_percent):  # Stop-loss
                    self.stop_loss(current_price)

            self.last_price = current_price
            self.last_volatility = self.current_volatility


        except BinanceAPIException as e:
            self.logger.error(f"Binance API error in execute_trade_logic: {e}")
            if e.code == -1021:  # Timestamp error; resync time
                self.logger.info("Attempting to resynchronize time due to time drift (Error -1021)...")
                self.sync_time() # Resync time with binance server.
                time.sleep(2)
        except Exception as e:
            self.logger.exception(f"An unexpected error occurred in execute_trade_logic: {e}") # Log any unexpected error with stack trace.

    def start(self):
        """Starts the bot's main loop in a separate thread."""
        if not self.running:  # Check if the bot is already running
            self.running = True  # Correctly set running to true
            self.thread = threading.Thread(target=self.run)  # Create thread object
            self.thread.start()  # Start trading thread
        else:
            self.logger.warning("Bot is already running.")

    def stop(self):
        self.running = False

    def buy(self, current_price, invest_amount):
        """Buys ETH (live or simulated)."""

        usdt_balance = self.get_balance('USDT')  # Get USDT balance

        if usdt_balance is None or usdt_balance == 0.0:  # Handle insufficient balance
            self.logger.error("Insufficient or unretrievable USDT balance. Cannot buy.")
            if self.is_live_trading:
                self.shutdown_bot()
            return

        if self.bought_price is None:  # Only buy if not already holding ETH
            try:
                if self.is_live_trading:  # Live Trading
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side=Client.SIDE_BUY,
                        type=Client.ORDER_TYPE_MARKET,
                        quoteOrderQty=invest_amount
                    )
                    self.logger.info(f"Buy order executed: {order}")

                    self.bought_price = float(order['fills'][0]['price']) # Get price from executed order

                    self.log_trade("Buy", self.bought_price, float(order['origQty'])) # Log the live trade

                    self.balance_usdt = self.get_balance('USDT')  # Update balances AFTER successful trade
                    self.eth_bal = self.get_balance('ETH')


                else:  # Test/Simulation Mode
                    quantity = round(invest_amount / current_price * (1 - self.trading_fee_percentage), 8) # Quantity with fee
                    cost_with_fee = quantity * current_price * (1 + self.trading_fee_percentage)

                    if usdt_balance >= cost_with_fee:  # Ensure sufficient balance for backtest
                        self.logger.info(f"Test - Buying {quantity} ETH at price: {current_price}")
                        self.eth_bal += quantity
                        self.balance_usdt -= cost_with_fee
                        self.bought_price = current_price
                        self.log_trade("Buy", current_price, quantity)  # Log the backtest buy

                    else:
                        self.logger.error(f"Test - Buy: Insufficient USDT balance. Available: {usdt_balance}, Needed: {cost_with_fee}, "
                                          f"current_price: {current_price}")


            except Exception as e:  # Catch any exceptions during buy
                self.logger.error(f"Error during buy (test/live): {e}")
        else:
            self.logger.info("Already bought, not buying again.")  # Prevent buying if already holding
            return

    def sell(self, current_price):
        """Sells ETH (live or simulated)."""

        if self.bought_price is not None and self.eth_bal > 0:  # Check for existing position
            try:
                if self.is_live_trading:
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side=Client.SIDE_SELL,
                        type=Client.ORDER_TYPE_MARKET,
                        quantity=self.eth_bal
                    )
                    self.logger.info(f"Sell order executed: {order}")
                    
                    profit = 0
                    if self.bought_price:
                         profit = ((float(order['fills'][0]['price']) - self.bought_price) / self.bought_price) * 100

                    self.log_trade("Sell", float(order['fills'][0]['price']), float(order['origQty']), None, profit)  # Log the live trade after success. Use filled price and quantity

                    # Update balances AFTER successful LIVE trade ONLY
                    self.balance_usdt = self.get_balance('USDT')
                    self.eth_bal = self.get_balance('ETH')

                else:  # Test Mode
                    self.log_trade("Sell", current_price, self.eth_bal)  # Log test trade before balance updates
                    self.logger.info(f"Test - Selling {self.eth_bal} ETH at price: {current_price}")
                    proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)
                    self.balance_usdt += proceeds
                    self.eth_bal = 0

                self.bought_price = None  # Reset bought_price after sell (live or test)
                return  # Add return statement after successful sell (or simulated sell)

            except Exception as e:
                self.logger.error(f"Error placing sell order: {e}")
                return # return if error

        else:
            self.logger.info("No ETH to sell or no previous buy order.")
            return  # Add return statement for this case as well


    def get_account_balance(self):
        """Retrieves the current USDT balance from Binance.US"""
        try:
            account_info = self.client.get_account()
            for balance in account_info['balances']:
                if balance['asset'] == 'USDT':
                    return float(balance['free'])
        except Exception as e:
            self.logger.error(f"Error getting account balance: {e}")
            return None

    def calculate_volatility(self):
        """Calculates the 14-day Average True Range (ATR) as a measure of volatility."""
        try:
            klines = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_1DAY, f"{self.volatility_period} day ago UTC")
            atr = 0.0
            for i in range(1, len(klines)):
                tr = max(
                    abs(float(klines[i][2]) - float(klines[i][3])),  # Current High - Current Low
                    abs(float(klines[i][2]) - float(klines[i-1][4])), # Current High - Previous Close
                    abs(float(klines[i][3]) - float(klines[i-1][4]))  # Current Low - Previous Close
                )
                atr += tr
            atr /= self.volatility_period
            return atr
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None

    def get_dynamic_stop_loss_percent(self, volatility):
        """Determines the stop-loss percentage based on volatility."""
        base_stop_loss_percent = 0.01  # 1% base stop loss
        volatility_multiplier = 0.1  # Adjust this multiplier to fine-tune the sensitivity

        stop_loss_percent = base_stop_loss_percent + (volatility * volatility_multiplier)
        return stop_loss_percent

    def stop_loss(self, current_price):
        """Triggers a stop-loss order if the price falls below a certain threshold."""

        if self.bought_price is not None and self.eth_bal > 0:  # Check for an existing position
            volatility = self.calculate_volatility()
            dynamic_stop_loss_percent = self.get_dynamic_stop_loss_percent(volatility) if volatility is not None else self.stop_loss_percent
            stop_loss_threshold = self.bought_price * (1 - dynamic_stop_loss_percent)

            if current_price < stop_loss_threshold:  # Check if stop-loss triggered
                try:
                    if self.is_live_trading:
                        order = self.client.create_order(
                            symbol=self.symbol,
                            side=Client.SIDE_SELL,
                            type=Client.ORDER_TYPE_MARKET,
                            quantity=self.eth_bal  # Sell entire ETH balance
                        )
                        self.logger.info(f"Stop loss order executed: {order}")

                        profit = 0
                        if self.bought_price:
                             profit = ((float(order['fills'][0]['price']) - self.bought_price) / self.bought_price) * 100

                        self.log_trade("Stop-loss Sell", float(order['fills'][0]['price']), float(order['origQty']), None, profit)

                        # Update balances after stop loss (Live Trading ONLY)
                        self.balance_usdt = self.get_balance('USDT')
                        self.eth_bal = self.get_balance('ETH')


                    else:  # Test/Simulation
                        self.log_trade("Stop-loss Sell", current_price, self.eth_bal)
                        self.logger.info(f"Test - Stop loss triggered. Selling {self.eth_bal} ETH at price: {current_price}")
                        proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)  # Proceeds after fees
                        self.balance_usdt += proceeds
                        self.eth_bal = 0

                    self.bought_price = None  # Reset bought_price after stop-loss

                    self.consecutive_stop_losses += 1
                    if self.consecutive_stop_losses >= 3:
                        self.stop()  # Stop the bot after 3 consecutive stop-losses
                        self.logger.info("Stopping bot due to 3 consecutive stop losses.")
                    return  # Exit after stop-loss execution (or simulation)

                except Exception as e:
                    self.logger.error(f"Error placing stop-loss order: {e}")
                    return # Return if there is an exception.

            else: # Reset consecutive stop losses if the price goes back up.
                self.consecutive_stop_losses = 0  # Reset counter if no stop-loss triggered in this check.
                return  # Exit if no action is taken within function.

        else:
            self.logger.info("No ETH to sell or no previous buy order.")
            return  # Exit if no action is taken within function

    def sell_on_ctrl_s(self):
        """Sells all ETH when Ctrl+Alt+S is pressed (pynput), regardless of price conditions."""

        if self.bought_price is not None and self.eth_bal > 0:  # Check for an open position before proceeding.
            try:
                current_price = self.check_price()
                if current_price is None:
                    self.logger.error("Error retrieving price in sell_on_ctrl_s().")
                    return  # Return immediately if price retrieval fails

                if self.is_live_trading:  # Live Trading
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side=Client.SIDE_SELL,
                        type=Client.ORDER_TYPE_MARKET,
                        quantity=self.eth_bal
                    )
                    self.logger.info(f"Sell order executed due to Ctrl+Alt+S: {order}")

                    profit = 0
                    if self.bought_price:
                         profit = ((float(order['fills'][0]['price']) - self.bought_price) / self.bought_price) * 100

                    self.log_trade("Ctrl+S Sell", float(order['fills'][0]['price']), float(order['origQty']), None, profit)

                    # Update balances AFTER successful trade (Live Trading ONLY)
                    self.balance_usdt = self.get_balance('USDT')
                    self.eth_bal = self.get_balance('ETH')

                else:  # Test/Simulation Mode
                    self.log_trade("Ctrl+S Sell", current_price, self.eth_bal)  # Log test trade before balance updates
                    self.logger.info(f"Test - Selling all {self.eth_bal} ETH due to Ctrl+Alt+S at price: {current_price}")
                    proceeds = self.eth_bal * current_price * (1 - self.trading_fee_percentage)  # Proceeds after fee.
                    self.balance_usdt += proceeds  # Add proceeds to balance
                    self.eth_bal = 0  # Reset ETH balance in test mode.

                self.bought_price = None  # Reset after a sell (live or test).

                self.shutdown_bot()  # Initiate shutdown after Ctrl+S sell
                return  # Exit function after sell (live or test) and shutdown.

            except Exception as e:  # Handle any errors during order placement
                self.logger.error(f"Error placing sell order on Ctrl+Alt+S: {e}")
                return  # Exit if an error occurs.


        else:
            self.logger.info("No ETH to sell or no previous buy order.")
            return  # Return if no action to be taken because of no position.

    def shutdown_bot(self):
        """Stops the bot and performs any necessary cleanup."""
        self.logger.info("Shutting down the bot...")
        if hasattr(self, 'hotkeys'):
            self.hotkeys.stop() # Stop hotkey listener.
        self.running = False
        self.stop()  # Stop the main loop

    def register_hotkeys(self):
        """Registers hotkeys for controlling the bot."""
        keyboard.add_hotkey("ctrl+s", self.sell_on_ctrl_s)


#-----------------------------Main Function-----------------------------#
def main():
    is_live_trading = input("Live trading? (y/n): ").lower() == 'y'
    filename = None

    if not is_live_trading:
        filename = input("Enter the filename for historical data: ")
    else:
        filename = 'ethereum_half_hourly_historical_data_2_days.csv'
    
    print("is_live_trading=", is_live_trading)

    bot = BinanceTradingBot(is_live_trading=is_live_trading, filename=filename) # Pass the filename


    if is_live_trading:
        print("Synchronizing time with Binance.US server... Please wait.")
        try:
            server_time = bot.client.get_server_time()
            bot.client.timestamp_offset = server_time['serverTime'] - int(time.time() * 1000)
            time.sleep(2)  # Brief pause after sync
            print("Time synchronized with Binance.US server.")
        except Exception as e:
            print(f"Error synchronizing time: {e}")
            return  # Exit if time sync fails

    # Get and print initial balances
    eth_balance = bot.get_balance('ETH')
    usdt_balance = bot.get_balance('USDT')
    btc_balance = bot.get_balance('BTC') # Retrieve balances before printing, prevent type error.
    print(f"\nInitial Balances:")
    print(f"  USDT: {usdt_balance if usdt_balance is not None else 0.0}")
    print(f"  ETH: {eth_balance if eth_balance is not None else 0.0}")
    print(f"  BTC: {btc_balance if btc_balance is not None else 0.0}")

    bot.check_trade_log_and_resume() # Check logs and resume here.
    bot.start()  # Start the bot's thread

    # if bot.is_live_trading: # Only use listener in live trading mode.
    #     try:
    #         with keyboard.Listener(
    #                 on_press=bot.on_press,
    #                 on_release=bot.on_release) as listener:
    #             listener.join()
    #     except AttributeError as e:
    #         bot.logger.error(f"AttributeError in pynput listener: {e}")

    #         if bot.is_live_trading:  # Handle this error in live trading by stopping bot
    #             bot.stop() # Stop the bot
    #             return # Do not continue execution.

    try:  # Main thread loop for Ctrl+C handling and backtesting
        while True:
            if not bot.is_live_trading and bot.finished_data or not bot.running:  # Check both conditions for exit in live and test.
                print("Bot has finished. Exiting.")
                break
            time.sleep(1)  # Check every 1 second

    except KeyboardInterrupt:
        print("Exiting via KeyboardInterrupt. Stopping Bot.")
        bot.stop() # Use stop() not shutdown_bot()


if __name__ == "__main__":
    main()