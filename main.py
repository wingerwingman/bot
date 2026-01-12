#!/usr/bin/env python3
"""
CryptoBot Main Entry Point

Usage:
    python main.py          # Start the API server (control via web UI)
    python main.py --cli    # Use terminal-based mode selection
"""
import sys
import os
import argparse
import time
import ctypes

def prevent_sleep():
    """
    Prevent Windows from going to sleep while the bot is running.
    ES_CONTINUOUS | ES_SYSTEM_REQUIRED = 0x80000000 | 0x00000001
    Does NOT prevent monitor from turning off (ES_DISPLAY_REQUIRED not used).
    """
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                0x80000000 | 0x00000001
            )
            print("⚡ Power Management: System Sleep DISABLED (Monitor can still sleep).")
        except Exception as e:
            print(f"⚠️ Could not set power state: {e}")

def main():
    prevent_sleep()
    parser = argparse.ArgumentParser(description='Binance Trading Bot')
    parser.add_argument('--cli', action='store_true', help='Use terminal/CLI mode instead of web UI')
    args = parser.parse_args()

    print("=" * 50)
    print("        CryptoBot - Binance Trading Bot")
    print("=" * 50)

    if args.cli:
        # Legacy CLI mode
        run_cli_mode()
    else:
        # Default: Start API server only, control via frontend
        run_server_mode()

def run_server_mode():
    """Start the API server and wait for commands from the web UI."""
    from modules import server
    
    print("\nStarting in SERVER mode...")
    print("Open http://localhost:3000 in your browser to control the bot.")
    print("Press Ctrl+C to stop the server.\n")
    
    server.start_server_standalone()
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)

def run_cli_mode():
    """Original terminal-based mode selection."""
    from modules.trading_bot import BinanceTradingBot
    
    mode = input("Select mode - (L)ive Trading or (T)est/Simulation? [l/t]: ").strip().lower()
    is_live = (mode == 'l')
    filename = None
    
    if not is_live:
        print("\nStarting simulation (backtest)...")
        data_dir = os.path.join(os.getcwd(), 'data')
        
        if os.path.exists(data_dir):
            files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
            if files:
                print("\nAvailable data files:")
                for i, f in enumerate(files):
                    print(f"  {i+1}. {f}")
                
                choice = input(f"\nEnter file number (default: 1): ").strip()
                
                if choice.isdigit() and 1 <= int(choice) <= len(files):
                    filename = os.path.join(data_dir, files[int(choice)-1])
                else:
                    filename = os.path.join(data_dir, files[0])
                
                print(f"Using: {filename}")
            else:
                print("No CSV files found in data/")
                return
        else:
            print("data/ directory not found")
            return
    else:
        print("Starting LIVE trading...")
        confirm = input("Trade with REAL MONEY? Type 'yes': ")
        if confirm != 'yes':
            print("Cancelled.")
            return
    
    bot = BinanceTradingBot(is_live_trading=is_live, filename=filename)
    bot.start()
    
    try:
        while bot.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        bot.stop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
