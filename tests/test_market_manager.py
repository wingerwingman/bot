import sys
import os
import time

# Add current directory to path
sys.path.append(os.getcwd())

from modules.market_data_manager import market_data_manager

def test_manager():
    print("Testing MarketDataManager...")
    try:
        # Try to get price (will trigger start_symbol)
        price = market_data_manager.get_price("BTCUSDT")
        print(f"Price for BTCUSDT: {price}")
        
        print("Waiting 5 seconds for WebSocket update...")
        time.sleep(5)
        
        new_price = market_data_manager.get_price("BTCUSDT")
        print(f"New Price for BTCUSDT: {new_price}")
        
        print("Test Passed!")
    except Exception as e:
        print(f"Test Failed: {e}")
    finally:
        market_data_manager.shutdown()

if __name__ == "__main__":
    test_manager()
