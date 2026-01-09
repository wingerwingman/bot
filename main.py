import sys
import os
from modules.trading_bot import BinanceTradingBot

def main():
    print("Welcome to the Binance Trading Bot")
    mode = input("Select mode - (L)ive Trading or (T)est/Simulation? [l/t]: ").lower()

    if mode == 'l':
        print("Starting LIVE trading...")
        # Confirm with user
        confirm = input("Are you SURE you want to trade with REAL MONEY? Type 'yes' to confirm: ")
        if confirm == 'yes':
            bot = BinanceTradingBot(is_live_trading=True)
            bot.start()
            try:
                # Keep main thread alive
                while bot.running:
                    bot.thread.join(1)
            except KeyboardInterrupt:
                bot.shutdown_bot()
        else:
            print("Live trading cancelled.")

    elif mode == 't' or mode == 'n': # 'n' for backward compatibility with 'no'
        print("Starting simulation (backtest)...")
        
        data_dir = 'data'
        filename = None
        
        # List available files
        if os.path.exists(data_dir):
            files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
            if files:
                print("\nAvailable data files:")
                for i, f in enumerate(files):
                    print(f"  {i+1}. {f}")
                print()
                
                choice = input(f"Enter file number or name (default: 1 - {files[0]}): ").strip()
                
                if not choice:
                    filename = os.path.join(data_dir, files[0])
                elif choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(files):
                        filename = os.path.join(data_dir, files[idx])
                    else:
                        print("Invalid selection number.")
                        return
                else:
                    # User typed a name, check normal path or data path
                    if os.path.exists(choice):
                        filename = choice
                    elif os.path.exists(os.path.join(data_dir, choice)):
                        filename = os.path.join(data_dir, choice)
                    else:
                        print(f"File '{choice}' not found.")
                        return
            else:
               print("No CSV files found in 'data/' directory.")
        
        if not filename:
             print("Could not determine data file.")
             filename = input("Enter full path to historical data CSV: ")
             if not os.path.exists(filename):
                 print("File not found.")
                 return

        print(f"Using data file: {filename}")
        bot = BinanceTradingBot(is_live_trading=False, filename=filename)
        bot.run() # Run synchronous in test mode
        
    else:
        print("Invalid mode selection.")

if __name__ == "__main__":
    main()
