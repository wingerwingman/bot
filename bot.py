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
    def __init__(self, api_key, api_secret,  test_mode=True):
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
        self.buy_threshold = 0.05  # Example threshold for buying when price drops by 5%
        self.sell_threshold = 0.04  # Example threshold for selling when price goes up by 10%
        self.stop_loss_threshold = 0.05  # Example stop loss threshold (price drop after buying)
        self.stop_loss_triggered = False
        self.bought_price = None
        self.eth_bal = 0

    def run(self):
        try:
            while self.running:
                if self.test_mode:
                    # Implement test mode logic
                    self.test()
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

        # Create a formatter and set it for the handler
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        ch.setFormatter(formatter)

        # Add the handler to the logger
        logger.addHandler(ch)
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

    def test(self):
        try:
            # Load historical price data from a CSV file
            historical_data = pd.read_csv('ethereum_historical_data.csv', dtype={'Price': float})

 
            # Loop through each row of historical data and simulate trading
            for index, row in historical_data.iterrows():
                # self.current_price = historical_data['Price']
                current_price = row['Price']  # Assuming the column name for price is 'Price'
                # Implement your trading strategy based on current price
                self.logger.info(f"Current price: {current_price}")
                print(f"Current price: {current_price}")
                time.sleep(10)
                if current_price < self.buy_threshold:
                    self.buy(current_price)
                    # print(current_price)
                    print("buy:") 
                    print(f"Balance after buying: {self.balance_usdt}")
                elif current_price > self.sell_threshold:
                    self.sell(current_price)
                    # print(current_price)
                    print("sell:")
                    print(f"Balance after selling: {self.balance_usdt}")
                elif current_price < (1 - self.stop_loss_threshold) * self.bought_price:
                    self.stop_loss(current_price)
                    # print(current_price)
                    print("sell:")
                    print(f"Balance after stop loss: {self.balance_usdt}")
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

    def buy(self, current_price):  # Added current_price as an argument
        # Implement buy logic using Binance API
        if self.bought_price is None:
            # Buy only if we haven't bought yet
            self.bought_price = current_price
            self.balance_usdt -= 100
            print("Test: Buying at price:", current_price)

    def sell(self, current_price):  # Added current_price as an argument
        # Implement sell logic using Binance API
        if self.bought_price is not None:
            profit_percentage = (current_price - self.bought_price) / self.bought_price * 100
            if profit_percentage >= 5 and current_price < (1 - 0.01) * self.bought_price:
                # Sell only if we have made profit of 5% and the price has dropped by 1%
                self.balance_usdt += 105  # Example: Add $105 to balance for selling
                print("Test: Selling at price:", current_price)
                self.bought_price = None

    def stop_loss(self, current_price):  # Added current_price as an argument
        # Implement stop loss logic
        if self.bought_price is not None:
            loss_percentage = (current_price - self.bought_price) / self.bought_price * 100
            if loss_percentage <= -1:
                # Sell if the price drops by 1% after buying
                print("Test: Stop loss triggered. Selling at price:", current_price)
                self.bought_price = None

def main():
    # Instantiate the BinanceTradingBot
    api_key = 'api_key'
    api_secret = 'api_secret'
    # client = Client(api_key, api_secret)
    # client.API_URL = 'https://api.binance.us'
    bot = BinanceTradingBot(api_key, api_secret, test_mode=True)

    # Start the bot
    bot.start()

    try:
        # Keep the main thread alive
        while True:
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