import os
import time
import logging
import threading
import pandas as pd
from binance.client import Client
# from binance.exceptions import BinanceAPIException
# from binance.enums import *

# api_url = "https://api.binance.us"
# binance_conn = Client(api_key, api_secret)
# binance_conn.API_URL = 'https://api.binance.us/api'
# binance_conn.WITHDRAW_API_URL = 'https://api.binance.us/wapi'
# binance_conn.MARGIN_API_URL = 'https://api.binance.us/sapi'
# binance_conn.WEBSITE_URL = 'https://www.binance.us'

class BinanceTradingBot:
    def __init__(self, api_key, api_secret, stop_loss_percent=None, sell_percent=None, test_mode=True):
        self.logger = self.setup_logger()
        # client = Client(api_key, api_secret, tld='us')
        # binance_conn = Client(api_key, api_secret)
        # binance_conn.API_URL = 'https://api.binance.us/api'
        # binance_conn.WITHDRAW_API_URL = 'https://api.binance.us/wapi'
        # binance_conn.MARGIN_API_URL = 'https://api.binance.us/sapi'
        # binance_conn.WEBSITE_URL = 'https://www.binance.us'
        self.api_key = os.environ.get('api_key')
        self.api_secret = os.environ.get('api_secret')
        # self.client.API_URL = 'https://api.binance.us'
        # client.api_url = "https://api.binance.us"
        # self.client = Client(api_key, api_secret)
        self.running = False
        self.test_mode = test_mode
        self.balance_usdt = 1000  # Initial USDT balance for testing
        self.symbol = 'ETHUSDT'
        self.buy_threshold = 0.0013724  # Example threshold for buying when price drops by 5%
        self.sell_threshold = 0.004  # Example threshold for selling when price goes up by 10%
        self.stop_loss_threshold = (1 + sell_percent) * 100 # Example stop loss threshold (price drop after buying)
        self.stop_loss_triggered = False
        self.bought_price = None
        self.eth_bal = 0
        self.initial_sell_threshold = 2000  # Set initial sell threshold
        self.initial_stop_loss_threshold = (1 - stop_loss_percent) * 100  # Set initial stop loss threshold
        self.sell_threshold = None  # Set initial sell threshold
        self.stop_loss_threshold = None  # Set initial stop loss threshold
        self.stop_loss_percent = stop_loss_percent
        self.sell_percent = sell_percent
        self.consecutive_stop_losses = 0
        self.stop_loss_triggered_last_time = False
        self.finished_data = False

    def run(self):
        try:
            while self.running:
                if self.test_mode:
                    # Implement test mode logic
                    self.test(stop_loss_percent=0.004, sell_percent=0.006)
                else:
                    # Implement live trading logic
                    self.live_trading()
                time.sleep(60)  # Adjust the interval as needed
        except Exception as e:
            print("An error occurred:", e)

    def setup_logger(self):
        logger = logging.getLogger("BinanceTradingBot")
        logger.setLevel(logging.DEBUG)

        # Create a console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # Create a file handler
        fh = logging.FileHandler('trading.log')
        fh.setLevel(logging.DEBUG)

        # Create a formatter and set it for the handlers
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        ch.setFormatter(formatter)
        fh.setFormatter(formatter)

        # Add the handlers to the logger
        logger.addHandler(ch)
        logger.addHandler(fh)
        return logger

    
    def check_price(self):
        if self.test_mode:
            # Simulate price checking in test mode
            # historical_data = pd.read_csv('ethereum_historical_data.csv', dtype={'Price': float})
            # # Get the first price from the CSV file
            # first_price = historical_data.iloc[0]['Price']
            # return first_price  # Example price in test mode
            return 500.0
        else:
            # Actual price checking using Binance API
            try:
                # Binance client initialization moved to live_trading method
                pass
            except Exception as e:
                print("Error:", e)
                return None

    def test(self, stop_loss_percent, sell_percent):
        try:
            # Load historical price data from a CSV file
            historical_data = pd.read_csv('ethereum_half_hourly_historical_data_2_days.csv', dtype={'Price': float})

            last_price = None

            # Loop through each row of historical data and simulate trading
            for index, row in historical_data.iterrows():
                current_price = row['Price']  # Assuming the column name for price is 'Price'
                self.logger.info(f"Current price: {current_price}")
                self.logger.info(f"Balance:  ${self.balance_usdt}, Eth {self.eth_bal}")
                # print(f"Current price: {current_price}")
                print(f"Current sell threshold: {sell_percent}")
                print(f"Current stop loss threshold: {stop_loss_percent}")
                # time.sleep(2)

                if last_price is not None:
                    percentage_change = ((current_price - last_price) / last_price) * 100
                    if percentage_change <= -.003:  # Example: Buy if price drops by 5% or more
                        if self.bought_price is None:  # Check if not already bought
                            self.buy(current_price)
                            print("buy:")
                            print(f"Balance after buying: {self.balance_usdt}, {self.eth_bal}")
                    elif self.bought_price is not None and (current_price - self.bought_price) / self.bought_price * 100 >= self.sell_percent:  # Sell if profit is at least sell_percent
                        self.sell(current_price)
                        print("sell:")
                        print(f"Balance after selling: {self.balance_usdt}, {self.eth_bal}")
                    elif self.bought_price is not None and (current_price - self.bought_price) / self.bought_price * 100 <= -self.stop_loss_percent:  # Stop loss if price drops by 20% or more
                        self.stop_loss(current_price)
                        print("sell:")
                        print(f"Balance after stop loss: {self.balance_usdt}, {self.eth_bal}")
                last_price = current_price

            self.finished_data = True
        except Exception as e:
            self.logger.error(f"An error occurred in test mode: {e}")

    def live_trading(self):
        self.client = Client(api_key, api_secret)
        current_price = self.check_price()  # Assuming you have a method to get the current price
        if current_price is None:
            return
        
        if self.bought_price is None:
            # Buy if not bought yet and price is down 5%
            if current_price < (1 - 0.05) * self.balance_usdt:
                # Initialize client only when needed (live trading mode)
                self.client = Client(api_key, api_secret)
                self.buy(current_price)
        else:
            # Check if profit threshold reached and price down 1%
            profit_percentage = (current_price - self.bought_price) / self.bought_price * 100
            if profit_percentage >= 5:  # Sell only if there's at least a 5% profit
                self.sell(current_price)
                print("sell:")
                print(self.balance_usdt)
            # Check stop loss
            elif current_price < (1 - 0.01) * self.bought_price:
                self.stop_loss(current_price)

    def start(self):
        self.running = True
        threading.Thread(target=self.run).start()

    def stop(self):
        self.running = False

    def buy(self, current_price):
        # Implement buy logic using Binance API
        invest_percentage = 0.1  # Example: Invest 10% of the current balance
        trading_fee_percentage = 0.01  # 1% trading fee

        if self.bought_price is None:
            # Buy only if we haven't bought yet
            invest_amount = self.balance_usdt * invest_percentage
            self.bought_price = current_price
            self.eth_bal = (invest_amount / current_price) * (1 - trading_fee_percentage)  # Adjusted for trading fee
            self.balance_usdt -= invest_amount * (1 + trading_fee_percentage)  # Adjusted for trading fee

            # Set the initial sell and stop loss thresholds
            self.sell_threshold = self.bought_price * 1.04  # 4% profit threshold
            self.stop_loss_threshold = self.bought_price * 0.80  # 20% stop loss threshold

            print(f"Bought at price: {current_price}, Invested amount: {invest_amount}, New balance: {self.balance_usdt}")
            print(f"Initial sell threshold: {self.sell_threshold}")
            print(f"Initial stop loss threshold: {self.stop_loss_threshold}")
        else:
            # Log that no purchase was made (since self.bought_price is not None)
            print(f"Already bought at price: {self.bought_price}. Cannot buy again.")

        # Additional logging for debugging
        print(f"Current balance after buy: {self.balance_usdt}")
        print(f"Current bought price: {self.bought_price}")

    def sell(self, current_price):
        # Implement sell logic using Binance API
        trading_fee_percentage = 0.01  # 1% trading fee

        if self.bought_price is not None:
            profit_percentage = (current_price - self.bought_price) / self.bought_price * 100
            if profit_percentage >= 4 and current_price >= self.bought_price * 1.04:  # Sell if profit is at least 4%
                # Sell only if we have made profit of at least 4% and the current price is at least 4% higher than the bought price
                sell_amount = self.eth_bal * (1 - trading_fee_percentage)  # Adjusted for trading fee
                self.balance_usdt += sell_amount * current_price * (1 - trading_fee_percentage)  # Adjusted for trading fee
                self.eth_bal -= sell_amount  # Update eth_bal
                self.bought_price = None
                print(f"Sold at price: {current_price}, Sold amount: {sell_amount}, New balance: {self.balance_usdt}")
            else:
                # Log the decision not to sell
                print(f"Not selling. Profit percentage: {profit_percentage:.2f}%")
        else:
            # Log that no previous purchase exists
            print("No previous purchase. Cannot sell.")

        print(f"Current balance after sell: {self.balance_usdt}")
        print(f"Current bought price after sell: {self.bought_price}")


    def stop_loss(self, current_price):
        # Implement stop loss logic
        self.logger.info(f"Current price: {current_price}")
        self.logger.info(f"Bought price: {self.bought_price}")

        if self.bought_price is not None:
            stop_loss_threshold = self.bought_price * (1 - self.stop_loss_percent)
            self.logger.info(f"Stop loss threshold: {stop_loss_threshold}")

            if current_price < stop_loss_threshold:
                # Increment the counter for consecutive stop-loss triggers
                if not self.stop_loss_triggered_last_time:
                    self.consecutive_stop_losses = 1
                    self.logger.info("Stop loss triggered.")
                else:
                    self.consecutive_stop_losses += 1

                # Execute stop loss only if price has dropped below the stop loss threshold
                stop_loss_amount = self.eth_bal * current_price
                self.balance_usdt += stop_loss_amount
                self.eth_bal = 0  # Reset the Ethereum balance to 0 after stop loss
                self.bought_price = None
                self.logger.info(f"Stop loss triggered at price: {current_price}, Recovered amount: {stop_loss_amount}, New balance: {self.balance_usdt}")
            else:
                # If the price has gone back up by a certain percentage, reset the counter
                if self.consecutive_stop_losses > 0:
                    self.consecutive_stop_losses -= 1

                # Log that stop loss was not triggered
                self.logger.info("Stop loss not triggered.")
                self.logger.info("Stop loss reset.")

            # Set flag for the last stop-loss trigger
            self.stop_loss_triggered_last_time = True if current_price < stop_loss_threshold else False

            # If consecutive stop losses exceed 3, stop the bot until the price goes back up by a certain percentage
            if self.consecutive_stop_losses >= 2:
                self.stop()
                self.logger.info("Stopping the bot due to three consecutive stop-loss triggers.")
        else:
            # Log that no previous purchase exists
            self.logger.info("No previous purchase. Cannot trigger stop loss.")

        # Additional logging for debugging
        self.logger.info(f"Current balance after stop loss: {self.balance_usdt}")
        self.logger.info(f"Current bought price after stop loss: {self.bought_price}")

def main():
    # Instantiate the BinanceTradingBot
    api_key = 'api_key'
    api_secret = 'api_secret'
    stop_loss_percent = 0.004
    sell_percent = 0.0003
    bot = BinanceTradingBot(api_key, api_secret, stop_loss_percent, sell_percent)

    # Start the bot
    bot.start()

    try:
        # Keep the main thread alive
        while True:
            # Check if the bot has finished processing historical data
            if bot.finished_data:
                print("Bot has finished processing historical data.")
                # Perform actions here, such as notifying the user
                break  # Exit the loop or continue with other tasks

            time.sleep(1)
    except KeyboardInterrupt:
        # Stop the bot when Ctrl+C is pressed
        bot.stop()

if __name__ == "__main__":
    main()

    

# Example usage:
# api_key = 'your_api_key'
# api_secret = 'your_api_secret'
# bot = BinanceTradingBot(api_key, api_secret)
# bot.start()

# api_key = 'your_api_key'
# api_secret = 'your_api_secret'
# bot = BinanceTradingBot(api_key, api_secret)
# bot.test_mode = True  # Set test mode to True
# bot.start()

# To stop the bot, you can call bot.stop()