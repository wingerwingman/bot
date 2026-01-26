import os
import re
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


# Import new modules using relative imports
from . import config
from . import indicators
from . import logger_setup
from . import notifier
from .strategy import Strategy

try:
    from .ml_predictor import TradePredictor
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("⚠️  ML Module (scikit-learn) not found. ML features will be disabled.")

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
                 dca_rsi_threshold=30,
                 allocated_capital=0.0,
                 # Advanced Filters (NEW: passed explicitly)
                 multi_timeframe_enabled=None,
                 volume_confirmation_enabled=None,
                 volume_multiplier=None,
                 cooldown_minutes=None,
                 missed_trade_log_enabled=None,
                 order_book_check_enabled=None,
                 support_resistance_check_enabled=None,
                 ml_confirmation_enabled=None):
        
        # Store for overrides (to prevent load_state from overwriting NEW settings)
        self._arg_multi_timeframe = multi_timeframe_enabled
        self._arg_volume_confirmation = volume_confirmation_enabled
        self._arg_volume_multiplier = volume_multiplier
        self._arg_cooldown = cooldown_minutes
        self._arg_missed_log = missed_trade_log_enabled
        self._arg_order_book = order_book_check_enabled
        self._arg_sr_check = support_resistance_check_enabled
        self._arg_ml_check = ml_confirmation_enabled
        
        self.slippage = slippage
        self.position_size_percent = position_size_percent
        self.dynamic_settings = dynamic_settings
        self.resume_state = resume_state
        self.dca_enabled = dca_enabled
        self.dca_rsi_threshold = dca_rsi_threshold
        self.allocated_capital = float(allocated_capital)
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
            dca_rsi_threshold=dca_rsi_threshold,
            # Pass arguments if provided, else fall back to config (ensures isolation)
            volume_confirmation_enabled=volume_confirmation_enabled if volume_confirmation_enabled is not None else config.VOLUME_CONFIRMATION_ENABLED,
            volume_multiplier=volume_multiplier if volume_multiplier is not None else config.VOLUME_MULTIPLIER_THRESHOLD,
            multi_timeframe_enabled=multi_timeframe_enabled if multi_timeframe_enabled is not None else config.MULTI_TIMEFRAME_ENABLED,
            cooldown_after_stoploss_minutes=cooldown_minutes if cooldown_minutes is not None else config.STOP_LOSS_COOLDOWN_MINUTES,
            missed_trade_log_enabled=missed_trade_log_enabled if missed_trade_log_enabled is not None else config.MISSED_TRADE_LOG_ENABLED,
            support_resistance_check_enabled=support_resistance_check_enabled if support_resistance_check_enabled is not None else config.SUPPORT_RESISTANCE_CHECK_ENABLED,
            ml_confirmation_enabled=ml_confirmation_enabled if ml_confirmation_enabled is not None else config.ML_CONFIRMATION_ENABLED,
            order_book_check_enabled=order_book_check_enabled if order_book_check_enabled is not None else config.ORDER_BOOK_CHECK_ENABLED
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
        
        # Health & Reliability (Phase 2)
        self.last_active_timestamp = time.time()
        self.ban_until = None
        self.consecutive_stop_losses = 0
        
        # Initialize ML Predictor (Imp 15)
        # Check either the argument or the strategy's internal state
        if self.strategy.ml_confirmation_enabled:
            if ML_AVAILABLE:
                self.logger.info("Initializing ML Predictor...")
                predictor = TradePredictor()
                if predictor.train():
                    self.strategy.set_ml_predictor(predictor)
                    self.logger.info("ML Predictor trained and attached to Strategy.")
                else:
                    self.logger.warning("ML Predictor failed to train (not enough data?). Confirmation disabled.")
            else:
                self.logger.warning("ML Feature enabled but scikit-learn not installed.")
        
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
                     raise RuntimeError(msg)
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
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.finished_data = False
        self.paused = False  # NEW: Pause state - bot tracks but doesn't trade
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
        self.total_fees = 0.0 # Track total fees (in Quote Asset approx)
        self.peak_balance = 0.0 # Will be set on start/resume
        self.max_drawdown = 0.0
        
        # --- NEW: TRADE DURATION TRACKING ---
        self.entry_time = None  # Timestamp when position was opened
        self.total_hold_time_minutes = 0  # Cumulative hold time
        self.trade_durations = []  # List of individual trade durations
        
        # --- NEW: SLIPPAGE TRACKING ---
        self.total_slippage = 0.0  # Cumulative slippage in quote currency
        self.slippage_events = []  # List of {expected, actual, difference}

        # --- NEW: STREAK TRACKING ---
        self.max_win_streak = 0
        self.max_loss_streak = 0

        # --- NEW: PERFORMANCE TRACKING (InMemory for Test/Paper) ---
        self.equity_history = []  # List of {timestamp, balance, pnl_percent}
        self.trade_journal = deque(maxlen=200) # Keep last 200 trades in memory


        
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
                
                # RE-APPLY OVERRIDES: Ensure settings passed to START command take precedence over loaded state
                if self._arg_multi_timeframe is not None:
                    self.logger.info(f"Applying OVERRIDE: multi_timeframe_enabled = {self._arg_multi_timeframe}")
                    self.strategy.multi_timeframe_enabled = self._arg_multi_timeframe
                if self._arg_volume_confirmation is not None:
                    self.logger.info(f"Applying OVERRIDE: volume_confirmation_enabled = {self._arg_volume_confirmation}")
                    self.strategy.volume_confirmation_enabled = self._arg_volume_confirmation
                if self._arg_volume_multiplier is not None:
                    self.strategy.volume_multiplier = self._arg_volume_multiplier
                if self._arg_cooldown is not None:
                    self.strategy.cooldown_after_stoploss_minutes = self._arg_cooldown
                if self._arg_missed_log is not None:
                    self.strategy.missed_trade_log_enabled = self._arg_missed_log
                if self._arg_order_book is not None:
                    self.logger.info(f"Applying OVERRIDE: order_book_check_enabled = {self._arg_order_book}")
                    self.strategy.order_book_check_enabled = self._arg_order_book
                if self._arg_sr_check is not None:
                    self.logger.info(f"Applying OVERRIDE: support_resistance_check_enabled = {self._arg_sr_check}")
                    self.strategy.support_resistance_check_enabled = self._arg_sr_check
                if self._arg_ml_check is not None:
                    self.logger.info(f"Applying OVERRIDE: ml_confirmation_enabled = {self._arg_ml_check}")
                    self.strategy.ml_confirmation_enabled = self._arg_ml_check
                    
                self.logger.debug("Applied startup overrides to resumed state.")
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

            # Format: "2026-01-15 10:38:50,286,Buy,0.00013,96931.95,1554.83"
            # The timestamp has a comma for milliseconds, so:
            # parts[0]: date time (without ms)
            # parts[1]: milliseconds
            # parts[2]: Action (Buy/Sell)
            # parts[3]: Quantity
            # parts[4]: Price
            # parts[5]: Balance (optional)
            if len(parts) >= 5:
                action = parts[2]
                quantity_str = parts[3]
                price_str = parts[4]
                
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
                            # Already holding position (loaded from state), so log check is redundant but confirms consistency.
                            self.logger.debug(f"Resume Check: Log indicates buy, and we are holding. State is consistent.")

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
        """Saves bot state to Database (SQLAlchemy)."""
        if not self.is_live_trading:
            return  # Don't save state for backtests

        try:
            from .database import db_session
            from .models import BotState

            session = db_session()
            
            # Upsert logic
            bot_state = session.query(BotState).filter_by(symbol=self.symbol).first()
            if not bot_state:
                bot_state = BotState(symbol=self.symbol)
                session.add(bot_state)

            bot_state.is_active = self.running
            bot_state.base_balance = self.base_balance
            bot_state.quote_balance = self.quote_balance
            bot_state.bought_price = self.bought_price
            bot_state.dca_count = self.dca_count
            bot_state.peak_price = self.strategy.peak_price_since_buy
            bot_state.stop_loss_price = self.bought_price * (1 - self.strategy.fixed_stop_loss_percent) if self.bought_price else None
            bot_state.last_volatility = self.last_volatility
            
            # Serialize Strategy Settings
            bot_state.configuration = {
                'rsi_threshold_buy': self.strategy.rsi_threshold_buy,
                'stop_loss_percent': self.strategy.stop_loss_percent,
                'fixed_stop_loss_percent': self.strategy.fixed_stop_loss_percent,
                'sell_percent': self.strategy.sell_percent,
                'dca_enabled': self.strategy.dca_enabled,
                'dca_rsi_threshold': self.strategy.dca_rsi_threshold,
                'volume_confirmation_enabled': self.strategy.volume_confirmation_enabled,
                'volume_multiplier': self.strategy.volume_multiplier,
                'multi_timeframe_enabled': self.strategy.multi_timeframe_enabled,
                'cooldown_after_stoploss_minutes': self.strategy.cooldown_after_stoploss_minutes,
                'missed_trade_log_enabled': self.strategy.missed_trade_log_enabled,
                'support_resistance_check_enabled': self.strategy.support_resistance_check_enabled,
                'ml_confirmation_enabled': self.strategy.ml_confirmation_enabled,
                'order_book_check_enabled': self.strategy.order_book_check_enabled,
                'ttp_activation_pct': self.strategy.ttp_activation_pct,
                'ttp_callback_pct': self.strategy.ttp_callback_pct,
                'dca_max_levels': self.strategy.dca_max_levels,
                'dca_multiplier': self.strategy.dca_multiplier,
                'sentiment_enabled': self.strategy.sentiment_enabled,
                'sentiment_threshold': self.strategy.sentiment_threshold
            }
            
            # Metrics
            bot_state.metrics = {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'gross_profit': self.gross_profit,
                'gross_loss': self.gross_loss,
                'peak_balance': self.peak_balance,
                'max_drawdown': self.max_drawdown,
                'max_win_streak': self.max_win_streak,
                'max_loss_streak': self.max_loss_streak,
                'consecutive_wins': self.consecutive_wins,
                'consecutive_losses': self.consecutive_losses
            }
            
            session.commit()
            # self.logger.debug(f"State saved to DB: bought_price={self.bought_price}")
            
        except Exception as e:
            self.logger.error(f"Error saving state to DB: {e}")
            session.rollback()
        finally:
            session.close()

    def load_state(self):
        """Loads bot state from Database (SQLAlchemy) on startup."""
        if not self.is_live_trading:
            return  # Don't load state for backtests

        try:
            from .database import db_session
            from .models import BotState
            
            session = db_session()
            state = session.query(BotState).filter_by(symbol=self.symbol).first()
            
            if not state:
                self.logger.debug("No previous state found in DB. Starting fresh.")
                session.close()
                return
                
            # Restore Metrics
            metrics = state.metrics or {}
            self.total_trades = metrics.get('total_trades', 0)
            self.winning_trades = metrics.get('winning_trades', 0)
            self.gross_profit = metrics.get('gross_profit', 0.0)
            self.gross_loss = metrics.get('gross_loss', 0.0)
            self.peak_balance = metrics.get('peak_balance', 0.0)
            self.max_drawdown = metrics.get('max_drawdown', 0.0)
            self.max_win_streak = metrics.get('max_win_streak', 0)
            self.max_loss_streak = metrics.get('max_loss_streak', 0)
            self.consecutive_wins = metrics.get('consecutive_wins', 0)
            self.consecutive_losses = metrics.get('consecutive_losses', 0)
            
            # Restore Strategy Settings
            config = state.configuration or {}
            self.strategy.rsi_threshold_buy = config.get('rsi_threshold_buy', self.strategy.rsi_threshold_buy)
            self.strategy.stop_loss_percent = config.get('stop_loss_percent', self.strategy.stop_loss_percent)
            self.strategy.fixed_stop_loss_percent = config.get('fixed_stop_loss_percent', self.strategy.fixed_stop_loss_percent)
            self.strategy.sell_percent = config.get('sell_percent', self.strategy.sell_percent)
            self.strategy.dca_enabled = config.get('dca_enabled', self.strategy.dca_enabled)
            self.strategy.dca_rsi_threshold = config.get('dca_rsi_threshold', self.strategy.dca_rsi_threshold)
            self.strategy.volume_confirmation_enabled = config.get('volume_confirmation_enabled', self.strategy.volume_confirmation_enabled)
            self.strategy.volume_multiplier = config.get('volume_multiplier', self.strategy.volume_multiplier)
            self.strategy.multi_timeframe_enabled = config.get('multi_timeframe_enabled', self.strategy.multi_timeframe_enabled)
            self.strategy.cooldown_after_stoploss_minutes = config.get('cooldown_after_stoploss_minutes', self.strategy.cooldown_after_stoploss_minutes)
            self.strategy.missed_trade_log_enabled = config.get('missed_trade_log_enabled', self.strategy.missed_trade_log_enabled)
            self.strategy.support_resistance_check_enabled = config.get('support_resistance_check_enabled', self.strategy.support_resistance_check_enabled)
            self.strategy.ml_confirmation_enabled = config.get('ml_confirmation_enabled', self.strategy.ml_confirmation_enabled)
            self.strategy.order_book_check_enabled = config.get('order_book_check_enabled', self.strategy.order_book_check_enabled)
            # Phase 3 & 5
            self.strategy.ttp_activation_pct = config.get('ttp_activation_pct', self.strategy.ttp_activation_pct)
            self.strategy.ttp_callback_pct = config.get('ttp_callback_pct', self.strategy.ttp_callback_pct)
            self.strategy.dca_max_levels = config.get('dca_max_levels', self.strategy.dca_max_levels)
            self.strategy.dca_multiplier = config.get('dca_multiplier', self.strategy.dca_multiplier)
            self.strategy.sentiment_enabled = config.get('sentiment_enabled', self.strategy.sentiment_enabled)
            self.strategy.sentiment_threshold = config.get('sentiment_threshold', self.strategy.sentiment_threshold)
            
            self.logger.info("Restored strategy settings from DB.")

            # Restore position info
            if state.bought_price:
                self.bought_price = state.bought_price
                self.base_balance = state.base_balance
                self.dca_count = state.dca_count or 0
                self.logger.debug(f"Restored position: bought_price={self.bought_price}, base_balance={self.base_balance}")
                print(f"🔄 Resuming position: Entry @ ${self.bought_price:.2f}, Qty: {self.base_balance:.6f}")

            # Restore Peak Price Logic
            if state.peak_price:
                self.strategy.peak_price_since_buy = float(state.peak_price)
                self.logger.debug(f"Restored Peak Price: ${self.strategy.peak_price_since_buy}")

            # Log restoration
            updated_at = state.updated_at.strftime("%Y-%m-%d %H:%M:%S") if state.updated_at else "Unknown"
            log_msg = (
                f"♻️ SESSION RESTORED from DB ({updated_at})\n"
                f"   • Symbol: {self.symbol}\n"
                f"   • Position: {'OPEN @ ' + str(self.bought_price) if self.bought_price else 'NO POSITION'}\n"
                f"   • Metrics: Net Profit ${self.gross_profit - self.gross_loss:.2f} ({self.total_trades} trades)\n"
                f"   • Peak Balance: ${self.peak_balance:.2f} (Max Drawdown: {self.max_drawdown*100:.2f}%)"
            )
            self.logger.debug(log_msg)
            print(log_msg)
            logger_setup.log_strategy(log_msg)

            self.last_volatility_check_time = None
            session.close()

        except Exception as e:
            self.logger.error(f"Error loading state from DB: {e}")

    def clear_state(self):
        """Clears the saved state (called after successful position close)."""
        if not self.is_live_trading:
            return

        state_file = self.get_state_file_path()
        if os.path.exists(state_file):
            # Don't delete, just update with no position
            self.save_state()
            self.logger.info("State cleared (position closed)")


    def update_support_resistance(self):
        """
        Updates S/R levels in the strategy using recent klines.
        Imp 6: Support/Resistance Awareness
        """
        if not config.SUPPORT_RESISTANCE_CHECK_ENABLED:
            return

        try:
            # Fetch 4H klines for S/R (Trend Timeframe)
            klines = self.client.get_klines(symbol=self.symbol, interval=config.TREND_TIMEFRAME, limit=config.SUPPORT_RESISTANCE_WINDOW)
            sr_data = indicators.calculate_support_resistance(klines, window=config.SUPPORT_RESISTANCE_WINDOW)
            
            if sr_data['support'] and sr_data['resistance']:
                self.strategy.set_support_resistance(sr_data['support'], sr_data['resistance'])
                # self.logger.debug(f"Updated S/R: Support=${sr_data['support']}, Resistance=${sr_data['resistance']}")
        except Exception as e:
            self.logger.error(f"Error updating S/R: {e}")

    def check_order_book(self):
        """
        Checks Order Book Depth/Spread.
        Imp 5: Order Book Depth
        Returns: True if safe to trade (liquid enough), False otherwise.
        """
        if not config.ORDER_BOOK_CHECK_ENABLED:
            return True
            
        try:
            depth = self.client.get_order_book(symbol=self.symbol)
            bids = depth['bids']
            asks = depth['asks']
            
            if not bids or not asks:
                return False
                
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread_pct = ((best_ask - best_bid) / best_bid) * 100
            
            # Log Spread (Imp 5 requirement)
            self.logger.info(f"Order Book: Bid=${best_bid}, Ask=${best_ask}, Spread={spread_pct:.4f}%")
            
            if spread_pct > 0.5: # 0.5% spread is too high for scalping
                self.logger.warning(f"High Spread ({spread_pct:.2f}%) - Order Book Check Failed")
                return False
                
            # Depth Ratio (Example Check)
            # sum top 5 bids vs top 5 asks volume
            bid_vol = sum([float(b[1]) for b in bids[:5]])
            ask_vol = sum([float(a[1]) for a in asks[:5]])
            
            if ask_vol > bid_vol * 3: # Huge sell wall?
                 # self.logger.warning(f"Sell Wall Detected (Ask Vol {ask_vol} > 3x Bid Vol {bid_vol})")
                 pass
                 
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking order book: {e}")
            return True # Fail safe: Allow if API fails? Or Block? Block is safer.
            
    def check_price(self):
        self.last_active_timestamp = time.time()
        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            if e.code == -1003:
                unban_str = ""
                try:
                     # Parse timestamp "IP banned until 1769278258028"
                     match = re.search(r'until\s+(\d+)', e.message)
                     if match:
                         ts = int(match.group(1)) / 1000.0
                         self.ban_until = ts # Store for auto-restart
                         dt = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                         unban_str = f"\n⏳ Ban Lifted At: {dt}"
                except:
                     pass

                self.logger.critical(f"🚨 IP BANNED BY BINANCE (Way too much request weight). Stopping Bot immediately.{unban_str}")
                self.running = False
                try:
                    notifier.send_telegram_message(f"🚨 <b>CRITICAL: IP BANNED</b>\nBot stopped to prevent extending ban.{unban_str}")
                except:
                    pass
                return None
            self.logger.error(f"Binance API Error: {e}")
            return None
        except (ConnectionError, TimeoutError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            self.logger.warning(f"Network Error (Retrying in 5s): {e}")
            time.sleep(5)
            return None
        except Exception as e:
            error_str = str(e)
            if "Connection aborted" in error_str or "RemoteDisconnected" in error_str or "NameResolutionError" in error_str or "Temporary failure in name resolution" in error_str or "Read timed out" in error_str or "Network is unreachable" in error_str:
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
                        free = float(balance['free'])
                        # Grid Bot Awareness: If Grid Bot is running, its funds are LOCKED. 
                        # This FREE balance is safe to use.
                        if hasattr(self, 'symbol') and self.symbol and asset == self.base_asset and os.path.exists(f"data/grid_state_{self.symbol}.json"):
                             self.logger.debug(f"Grid Bot active. Using free {asset}: {free} (Grid funds locked)")
                        return free
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
                # self.logger.debug(f"Fear & Greed Index: {value} ({classification})")

                # Also log to Strategy Tab
                # logger_setup.log_strategy(f"Fear & Greed Index: {value} ({classification})")
                return value
            return 50 # Neutral default
        except Exception as e:
            self.logger.error(f"Error fetching Fear & Greed Index: {e}")
            return 50

    def fetch_higher_timeframe_trend(self):
        """
        Fetches 4H klines and calculates trend using MA50.
        Updates strategy's higher_tf_trend cache.
        """
        try:
            # Fetch 4H data (need 50+ candles for MA50)
            klines = self.client.get_historical_klines(
                self.symbol, 
                Client.KLINE_INTERVAL_4HOUR, 
                "10 days ago UTC"  # ~60 candles
            )
            
            trend_data = indicators.calculate_higher_timeframe_trend(klines, ma_period=50)
            self.strategy.set_higher_timeframe_trend(trend_data)
            
            if trend_data['trend'] != 'neutral':
                self.logger.debug(f"4H Trend: {trend_data['trend'].upper()} (MA50: ${trend_data['ma_value']:.2f})")
            
            return trend_data
        except Exception as e:
            self.logger.error(f"Error fetching 4H trend: {e}")
            return {'trend': 'neutral', 'ma_value': None, 'current_price': None}

    def fetch_current_volume(self):
        """
        Fetches the current candle's volume from Binance.
        Returns volume in base asset units.
        """
        try:
            # Get last 2 candles (current + previous for comparison)
            klines = self.client.get_klines(symbol=self.symbol, interval='15m', limit=2)
            if klines and len(klines) >= 1:
                current_volume = float(klines[-1][5])  # Volume is index 5
                return current_volume
            return None
        except Exception as e:
            self.logger.error(f"Error fetching volume: {e}")
            return None

    def calculate_slippage(self, expected_price, actual_price, quantity):
        """
        Calculates and records slippage for a trade.
        
        Args:
            expected_price: Price at signal time
            actual_price: Actual fill price
            quantity: Trade quantity
        
        Returns:
            Slippage amount in quote currency
        """
        slippage_per_unit = abs(actual_price - expected_price)
        slippage_amount = slippage_per_unit * quantity
        slippage_percent = (slippage_per_unit / expected_price) * 100 if expected_price > 0 else 0
        
        # Record event
        event = {
            'expected': expected_price,
            'actual': actual_price,
            'quantity': quantity,
            'slippage_amount': slippage_amount,
            'slippage_percent': slippage_percent,
            'timestamp': datetime.datetime.now().isoformat()
        }
        self.slippage_events.append(event)
        self.total_slippage += slippage_amount
        
        if slippage_percent > 0.1:  # Log if slippage > 0.1%
            self.logger.info(f"Slippage: Expected ${expected_price:.2f}, Got ${actual_price:.2f} ({slippage_percent:.2f}%)")
        
        return slippage_amount

    def record_trade_duration(self):
        """
        Records the duration of a completed trade.
        Call this when closing a position.
        
        Returns:
            Duration in minutes, or 0 if no entry_time recorded
        """
        if self.entry_time is None:
            return 0
        
        duration_seconds = time.time() - self.entry_time
        duration_minutes = duration_seconds / 60
        
        self.trade_durations.append(duration_minutes)
        self.total_hold_time_minutes += duration_minutes
        self.entry_time = None  # Reset for next trade
        
        return duration_minutes

    def get_average_trade_duration(self):
        """Returns average trade duration in minutes."""
        if not self.trade_durations:
            return 0
        return sum(self.trade_durations) / len(self.trade_durations)

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
                    risk_percent = 0.02 # Stable risk in extreme fear (Quality > Quantity)
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
            # Check allocated capital limit (Fix for Allocation Slider)
            max_spendable = self.quote_balance
            if self.allocated_capital > 0:
                max_spendable = min(self.quote_balance, self.allocated_capital)

            max_units = (max_spendable / current_price) * 0.99 # 99% to cover fees
            
            final_units = min(position_units, max_units)
            
            self.logger.debug(f"Dynamic Sizing: Risk ${risk_amount:.2f} (2%), Dist ${distance_per_unit:.2f}, Calc Units {position_units:.4f}, Cap {max_units:.4f} (Alloc: {self.allocated_capital})")
            return final_units
            
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            # Fallback to fixed %
            balance = self.get_balance(self.quote_asset)
            if self.allocated_capital > 0:
                balance = min(balance, self.allocated_capital)
            invest_amount = balance * self.position_size_percent
            return invest_amount / current_price




    def shutdown_bot(self):
        self.logger.info("Shutting down the bot...")
        self.stop()

    def print_performance_report(self):
        """Prints the current performance report with Enhanced Analytics."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        profit_factor = (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else 999.0
        avg_duration = self.get_average_trade_duration()
        net_pnl = self.gross_profit - self.gross_loss
        
        print("\n" + "="*40)
        print(f"       SESSION PERFORMANCE REPORT       ")
        print("="*40)
        print(f"Trades: {self.total_trades} (Win: {self.winning_trades})")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Profit Factor: {profit_factor:.2f}")
        print(f"Max Win Streak:  {self.max_win_streak}")
        print(f"Max Loss Streak: {self.max_loss_streak}")
        print(f"Max Drawdown:    {self.max_drawdown*100:.2f}%")
        print(f"Avg Duration:    {avg_duration:.1f} min")
        
        # Imp 9: Live P&L Thermometer
        print("\n--- 🌡️ SESSION P&L ---")
        pnl_blocks = int(net_pnl * 2) # Every $0.50 profit = 1 block? Or scale dynamically. 
        # Simple scale:
        if net_pnl > 0:
            bar = "🟩" * min(10, int(net_pnl))
            print(f"P&L: ${net_pnl:.2f} {bar}")
        elif net_pnl < 0:
            bar = "🟥" * min(10, int(abs(net_pnl)))
            print(f"P&L: -${abs(net_pnl):.2f} {bar}")
        else:
            print("P&L: $0.00 ⬜")

        if self.total_slippage > 0:
            avg_slippage = self.total_slippage / len(self.slippage_events) if self.slippage_events else 0
            print(f"Total Slippage:  ${self.total_slippage:.2f} (Avg: ${avg_slippage:.2f}/trade)")
        
        # Imp 10: Strategy Settings Comparison
        print("\n--- 🔧 STRATEGY SETTINGS ---")
        print(f"Current RSI Threshold: {self.strategy.rsi_threshold_buy} (Default: 40)")
        print(f"Current Stop Loss:     {self.strategy.fixed_stop_loss_percent*100:.1f}% (Default: {config.DEFAULT_VOLATILITY_PERIOD*0.1:.1f}%)")
        print(f"ML Confirmation:       {'ON' if self.strategy.ml_confirmation_enabled else 'OFF'}")
        
        # Imp 8: Heat Map (Simple Text Version)
        if config.HEATMAP_CALCULATION_ENABLED and self.total_trades > 5:
            print("\n--- 🔥 HOURLY HEATMAP ---")
            # Calculate from journal (requires journal to be populated correctly)
            hour_pnl = {}
            for t in self.trade_journal:
                # Approximate hour from timestamp if available or just skip for now
                pass
            print("(Requires more trade history for heatmap)")

        print("="*40 + "\n")

    def update_metrics(self, profit_amount, current_equity):
        """Updates internal metrics after a trade close."""
        self.total_trades += 1
        if profit_amount > 0:
            self.winning_trades += 1
            self.gross_profit += profit_amount
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            if self.consecutive_wins > self.max_win_streak:
                self.max_win_streak = self.consecutive_wins
        else:
            self.gross_loss += abs(profit_amount)
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            if self.consecutive_losses > self.max_loss_streak:
                self.max_loss_streak = self.consecutive_losses
            
            # Consecutive losses alert
            if self.consecutive_losses >= 3 and self.is_live_trading:
                notifier.send_telegram_message(
                    f"⚠️ <b>WARNING: LOSS STREAK ({self.symbol})</b>\n"
                    f"Bot has reached {self.consecutive_losses} consecutive losses.\n"
                    f"Consider pausing or reviewing settings."
                )
            
        # Drawdown logic
        if current_equity > self.peak_balance:
            self.peak_balance = current_equity
        
        if self.peak_balance > 0.01:
            drawdown = (self.peak_balance - current_equity) / self.peak_balance
            # Ensure drawdown is a ratio (0.0 to 1.0)
            drawdown = max(0.0, min(1.0, drawdown))
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

        # Equity Snapshot for Sharpe Ratio
        pnl_percent = 0.0
        if self.bought_price and self.bought_price > 0:
             # This assumes update_metrics is called AFTER sell/close, but we don't pass executed price here
             # We can approximate pnl_percent from profit_amount / cost_basis if tracked, 
             # or just pass it in. For now, let's use the equity change.
             pass 

        timestamp = datetime.datetime.now().isoformat()
        self.equity_history.append({
            'timestamp': timestamp,
            'balance': current_equity,
            'profit_amount': profit_amount
        })

    def get_sharpe_ratio(self, risk_free_rate=0.02):
        """Calculates Sharpe Ratio from internal equity history."""
        if len(self.equity_history) < 2:
            return 0.0
        
        # Calculate PnL percentages from equity changes
        returns = []
        for i in range(1, len(self.equity_history)):
            prev = self.equity_history[i-1]['balance']
            curr = self.equity_history[i]['balance']
            if prev > 0:
                ret = (curr - prev) / prev
                returns.append(ret)
        
        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)
        
        if std_return == 0:
            return 0.0
            
        # Annualize (Crypto ~365 days) assuming daily trades? 
        # Actually this is per-trade Sharpe.
        # Approximation: Annualized = PerTrade * sqrt(N_trades_per_year)
        # Let's return raw per-trade Sharpe for now or standard simplification
        # Standard: (Mean - Rf) / StdDev. Rf per trade is negligible usually.
        
        sharpe = mean_return / std_return
        return round(sharpe, 2)

    def get_performance_summary(self):
        """Returns a comprehensive performance dictionary."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        profit_factor = (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else 999.0
        
        # Avg Return (per trade)
        avg_return = 0.0
        if self.total_trades > 0:
            net_pnl = self.gross_profit - self.gross_loss
            # As percentage of starting balance? 
            # Or average of individual trade percentages?
            # Let's use average trade PnL % from history if available, else simple approx
            avg_return = (self.total_return if hasattr(self, 'total_return') else 0.0) / self.total_trades
            
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.total_trades - self.winning_trades,
            'win_rate': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(self.max_drawdown * 100, 2),
            'sharpe_ratio': self.get_sharpe_ratio(),
            'max_win_streak': self.max_win_streak,
            'max_loss_streak': self.max_loss_streak,
            'net_profit': self.gross_profit - self.gross_loss,
            'avg_duration': round(self.get_average_trade_duration(), 1)
        }

    def get_internal_journal(self):
        """Returns the in-memory trade journal."""
        # Convert deque to list and return reversed (newest first)
        return list(self.trade_journal)


    def start(self):
        if not self.running:
            self.running = True
            self.start_time = time.time() # Track startup time for warmup
            # Set initial peak balance for metrics
            self.peak_balance = self.get_balance(self.quote_asset) + (self.get_balance(self.base_asset) * (self.check_price() or 0))
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
        else:
            self.logger.warning("Bot is already running.")

    def stop(self):
        self.running = False
        
        # Send shutdown notification with final stats (only if bot was fully initialized)
        if self.is_live_trading and hasattr(self, 'symbol') and self.symbol:
            try:
                net_pnl = self.gross_profit - self.gross_loss
                win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
                
                stop_msg = (
                    f"🛑 <b>SPOT BOT STOPPED</b>\n"
                    f"Symbol: {self.symbol}\n"
                    f"\n📊 <b>Final Session Stats:</b>\n"
                    f"Trades: {self.total_trades} (Win: {self.winning_trades})\n"
                    f"Win Rate: {win_rate:.1f}%\n"
                    f"Net P&L: ${net_pnl:.2f}\n"
                    f"Total Fees: ${self.total_fees:.2f}\n"
                    f"Max Drawdown: {self.max_drawdown:.2f}%\n"
                    f"Final Balance: ${self.quote_balance:.2f}"
                )
                notifier.send_telegram_message(stop_msg)
            except Exception as e:
                self.logger.error(f"Error sending stop notification: {e}")

    def pause(self):
        """Pause trading - bot continues tracking but won't execute trades."""
        if not self.paused:
            self.paused = True
            self.logger.info("Bot PAUSED - tracking continues, trading suspended")
            if self.is_live_trading:
                notifier.send_telegram_message(f"⏸️ <b>BOT PAUSED</b>\nSymbol: {self.symbol}\nTrading suspended, monitoring continues.")
    
    def resume(self):
        """Resume trading after pause."""
        if self.paused:
            self.paused = False
            self.logger.info("Bot RESUMED - trading active")
            if self.is_live_trading:
                notifier.send_telegram_message(f"▶️ <b>BOT RESUMED</b>\nSymbol: {self.symbol}\nTrading active.")

    def _fetch_real_fee(self, order_id):
        """Fetch actual commission paid for an order and convert to USDT."""
        if not self.is_live_trading:
            return None
        
        try:
            trades = self.client.get_my_trades(symbol=self.symbol, orderId=order_id)
            total_fee_usdt = 0.0
            
            for t in trades:
                fee = float(t['commission'])
                asset = t['commissionAsset']
                
                if asset in ['USDT', 'USD']:
                    total_fee_usdt += fee
                elif asset == 'BNB':
                    try:
                        ticker = self.client.get_symbol_ticker(symbol="BNBUSDT")
                        price = float(ticker['price'])
                        total_fee_usdt += fee * price
                    except:
                        self.logger.warning("Could not fetch BNB price for fee calc. Using $600 fallback.")
                        total_fee_usdt += fee * 600.0 
                elif asset == self.base_asset or asset == self.symbol.replace('USDT',''):
                    trade_price = float(t['price'])
                    total_fee_usdt += fee * trade_price
            
            if len(trades) > 0:
                self.logger.info(f"🧾 Actual Fee Fetched: ${total_fee_usdt:.4f} (from {len(trades)} fills)")
                return total_fee_usdt
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to fetch real fee: {e}")
            return None

    def buy(self, current_price, invest_amount, is_dca=False):
        if is_dca: self.last_dca_attempt = time.time()
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
                             msg = f"🛡️ DEFENSE BUY #{self.dca_count} FILLED. New Avg Price: {self.bought_price:.2f}"
                             self.logger.info(msg)
                             logger_setup.log_strategy(msg)
                        else:
                             self.bought_price = cummulative_quote_qty / executed_qty
                             self.dca_count = 0 # Reset on fresh buy
                             
                             # NEW: Record entry time for trade duration tracking
                             self.entry_time = time.time()
                        
                        # NEW: Calculate slippage (expected vs actual)
                        self.calculate_slippage(current_price, self.bought_price, executed_qty)
                    else:
                        self.bought_price = float(order['fills'][0]['price']) # Fallback
                    
                    self.quote_balance = self.get_balance(self.quote_asset)
                    self.base_balance = self.get_balance(self.base_asset)
                    
                    total_val = self.quote_balance + (self.base_balance * self.bought_price)
                    
                    self.logger.info(f"Order Filled: Bought {executed_qty} {self.base_asset} @ {self.bought_price:.2f} (Total {cummulative_quote_qty} {self.quote_asset})")
                    
                    # Enhanced Telegram with context
                    buy_msg = (
                        f"🟢 <b>BUY EXECUTION</b>\n"
                        f"Symbol: {self.symbol}\n"
                        f"Price: ${self.bought_price:.2f}\n"
                        f"Qty: {executed_qty:.6f}\n"
                        f"Total: ${cummulative_quote_qty:.2f}\n"
                        f"\n📊 <b>Position Status:</b>\n"
                        f"Remaining {self.quote_asset}: ${self.quote_balance:.2f}\n"
                        f"Holdings: {self.base_balance:.6f} {self.base_asset}"
                    )
                    if self.dca_count > 0:
                        buy_msg += f"\n⚡ DCA Level: {self.dca_count}"
                    notifier.send_telegram_message(buy_msg)
                    
                    logger_setup.log_trade(self.logger, self.trade_logger, "Buy", self.bought_price, executed_qty, cummulative_quote_qty, is_test=False)
                    
                    # Track Fees (Estimate: Quote Qty * Fee Rate)
                    # Note: If BNB is used, value is same.
                    real_fee = self._fetch_real_fee(order['orderId'])
                    if real_fee is not None:
                        self.total_fees += real_fee
                    else:
                        est_fee = cummulative_quote_qty * self.trading_fee_percentage
                        self.total_fees += est_fee
                    
                    # Save state after buy for crash recovery
                    self.save_state()
                    
                    # === TRADE JOURNAL ENTRY ===
                    try:
                        rsi_val = indicators.calculate_rsi(self.strategy.price_history) if len(self.strategy.price_history) > 14 else None
                        macd, hist, sig = indicators.calculate_macd(self.strategy.price_history)
                        
                        journal_entry = {
                            'action': 'BUY',
                            'symbol': self.symbol,
                            'price': self.bought_price,
                            'qty': executed_qty,
                            'total_value': cummulative_quote_qty,
                            'fee': float(real_fee if real_fee else est_fee),
                            'entry_reason': 'DCA Defense' if is_dca else 'Signal Buy',
                            'dca_level': self.dca_count,
                            'indicators': {
                                'rsi': round(rsi_val, 2) if rsi_val else None,
                                'macd_hist': round(hist, 4) if hist else None,
                                'volatility': round(self.last_volatility * 100, 2) if self.last_volatility else None,
                                'fear_greed': self.fear_greed_index
                            },
                            'balance_after': self.quote_balance
                        }
                        logger_setup.log_trade_journal(journal_entry)
                    except Exception as e:
                        self.logger.debug(f"Error logging to trade journal: {e}")
                else:
                    quantity = round(invest_amount / current_price * (1 - self.trading_fee_percentage), 8)
                    cost_with_fee = quantity * current_price * (1 + self.trading_fee_percentage)
                    
                    if quote_bal >= cost_with_fee:
                        if is_dca:
                            # Weighted Average for Sim
                            total_cost = (self.base_balance * self.bought_price) + (quantity * current_price)
                            total_qty = self.base_balance + quantity
                            self.bought_price = total_cost / total_qty
                            self.dca_count += 1
                        else:
                            self.bought_price = current_price
                            self.dca_count = 0
                            self.entry_time = time.time()

                        self.base_balance += quantity
                        self.quote_balance -= cost_with_fee
                        logger_setup.log_trade(self.logger, self.trade_logger, "Buy" if not is_dca else "DCA Buy", current_price, quantity, quantity * current_price, is_test=True)
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
                     
                     # Metrics Update via Helper
                     self.update_metrics(profit_amount, self.quote_balance)
                     
                     net_pnl = self.gross_profit - self.gross_loss
                     win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
                     
                     # NEW: Record trade duration
                     trade_duration = self.record_trade_duration()
                     
                     # NEW: If this was a stop-loss, record for cooldown
                     if reason == 'Stop-loss Sell':
                         self.strategy.record_stoploss()
                         self.logger.info(f"Cooldown activated for {self.strategy.cooldown_after_stoploss_minutes} minutes")
                     
                     # NEW: Calculate sell slippage
                     self.calculate_slippage(current_price, avg_price, executed_qty)
                     
                     pnl_emoji = "🟢" if profit_amount >= 0 else "🔴"
                     
                     # Enhanced Telegram with performance summary
                     sell_msg = (
                         f"{pnl_emoji} <b>SELL EXECUTION</b>\n"
                         f"Symbol: {self.symbol}\n"
                         f"Price: ${avg_price:.2f}\n"
                         f"Qty: {executed_qty:.6f}\n"
                         f"Revenue: ${revenue:.2f}\n"
                         f"Trade PnL: ${profit_amount:.2f} ({real_profit_percent:.2f}%)\n"
                         f"\n📈 <b>Session Performance:</b>\n"
                         f"Trades: {self.total_trades} (Win: {self.winning_trades})\n"
                         f"Win Rate: {win_rate:.1f}%\n"
                         f"Net P&L: ${net_pnl:.2f}\n"
                         f"Total Fees: ${self.total_fees:.2f}\n"
                    f"Max Drawdown: {self.max_drawdown:.2f}%\n"
                         f"\n💰 Balance: ${self.quote_balance:.2f}"
                     )
                     notifier.send_telegram_message(sell_msg)
                     
                     logger_setup.log_trade(self.logger, self.trade_logger, reason, avg_price, executed_qty, revenue, real_profit_percent, is_test=False)
                     
                     # Track Fees (Approx Revenue * Fee Rate)
                     # Track Fees
                     real_fee = self._fetch_real_fee(order['orderId'])
                     if real_fee is not None:
                         self.total_fees += real_fee
                     else:
                         est_fee = revenue * self.trading_fee_percentage
                         self.total_fees += est_fee
                     
                     # Update drawdown tracking
                     current_equity = self.quote_balance 
                     if current_equity > self.peak_balance:
                         self.peak_balance = current_equity
                     if self.peak_balance > 0:
                         dd = ((self.peak_balance - current_equity) / self.peak_balance) * 100
                         if dd > self.max_drawdown:
                             self.max_drawdown = dd
                     
                     self.print_performance_report()
                     
                     # === TRADE JOURNAL & EQUITY LOGGING ===
                     try:
                         rsi_val = indicators.calculate_rsi(self.strategy.price_history) if len(self.strategy.price_history) > 14 else None
                         macd, hist, sig = indicators.calculate_macd(self.strategy.price_history)
                         
                         journal_entry = {
                             'timestamp': datetime.datetime.now().isoformat(),
                             'action': 'SELL',
                             'symbol': self.symbol,
                             'price': avg_price,
                             'qty': executed_qty,
                             'total_value': revenue,
                             'fee': float(real_fee if real_fee is not None else est_fee),
                             'exit_reason': reason,
                             'pnl_percent': round(real_profit_percent, 2),
                             'pnl_amount': round(profit_amount, 2),
                             'entry_price': self.bought_price if hasattr(self, '_last_entry_price') else None,
                             'entry_value': (self.bought_price * executed_qty) if self.bought_price else None, # Cost Basis
                             'indicators': {
                                 'rsi': round(rsi_val, 2) if rsi_val else None,
                                 'macd_hist': round(hist, 4) if hist else None,
                                 'volatility': round(self.last_volatility * 100, 2) if self.last_volatility else None,
                                 'fear_greed': self.fear_greed_index
                             },
                             'session_stats': {
                                 'total_trades': self.total_trades,
                                 'win_rate': round(win_rate, 1),
                                 'net_pnl': round(net_pnl, 2)
                             },
                             'balance_after': self.quote_balance
                         }
                         # Log to Global Journal (Live Only or Persistent)
                         logger_setup.log_trade_journal(journal_entry)
                         
                         # Log to Internal Journal (For Paper/Test Dashboard visibility)
                         self.trade_journal.appendleft(journal_entry)

                         
                         # Log equity snapshot for Sharpe Ratio
                         logger_setup.log_equity_snapshot(self.quote_balance, real_profit_percent)
                     except Exception as e:
                         self.logger.debug(f"Error logging to trade journal: {e}")

                else:
                    revenue = self.base_balance * current_price * (1 - self.trading_fee_percentage)
                    profit_amount = revenue - (self.base_balance * self.bought_price)
                    
                    qty_sold = self.base_balance
                    self.quote_balance += revenue
                    self.log_trade_wrapper(reason, current_price, qty_sold, self.quote_balance, profit)
                    self.base_balance = 0
                    
                    # Metrics Update via Helper
                    self.update_metrics(profit_amount, self.quote_balance)
                    
                    self.logger.info(f"Test Sale: {qty_sold} {self.base_asset} @ {current_price:.2f} | PnL: ${profit_amount:.2f}")
                
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
        try:
            if self.is_live_trading:
                # Re-check resume logic
                self.check_trade_log_and_resume()
                
            # FREQUENCY UPDATE: Check every 5 minutes (User Preference)
            volatility_check_interval = 5 * 60 
            last_heartbeat_time = time.time()
            
            self.logger.debug("Entering main trading loop...")
            # PAPER TRADING INITIALIZATION
            if not self.is_live_trading and self.filename is None:
                self.logger.info("Initializing PAPER TRADING (Live Market / Simulated Orders)")
                self.quote_balance = 1000.0 # Default starting balance
                if self.allocated_capital > 0:
                    self.quote_balance = self.allocated_capital
                self.peak_balance = self.quote_balance

            if self.is_live_trading or self.filename is None:
                # Send startup notification
                start_msg = (
                    f"🚀 <b>SPOT BOT STARTED</b>\n"
                    f"Symbol: {self.symbol}\n"
                    f"Mode: {'🟢 LIVE' if self.is_live_trading else '🧪 PAPER (SIM)'}\n"
                    f"Balance: ${self.quote_balance:.2f} {self.quote_asset}\n"
                    f"Holdings: {self.base_balance:.6f} {self.base_asset}\n"
                    f"Dynamic Tuning: {'ON' if self.dynamic_settings else 'OFF'}\n"
                    f"DCA Defense: {'ON' if self.dca_enabled else 'OFF'}"
                )
                notifier.send_telegram_message(start_msg)
                
                if self.is_live_trading:
                    self.peak_balance = max(self.peak_balance, self.quote_balance)
                
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
                             
                             # EXPOSE FOR UI
                             self.current_trail_price = trail_price
                             self.current_hard_stop = sl_price
                             
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
                        
                        # Save State Periodically (every 5 mins) to persist Trail Data and Settings
                        if self.is_live_trading:
                            self.save_state()
                        
                        # --- VOLATILITY CHANGE ALERT (>20% shift) ---
                        if old_volatility is not None and self.last_volatility is not None:
                            vol_change_pct = abs(self.last_volatility - old_volatility) / old_volatility if old_volatility > 0 else 0
                            if vol_change_pct > 0.20:  # >20% change
                                direction = "↑ INCREASED" if self.last_volatility > old_volatility else "↓ DECREASED"
                                msg = f"🌊 VOLATILITY SHIFT: {direction} {vol_change_pct*100:.0f}% | Was: {old_volatility*100:.2f}% → Now: {self.last_volatility*100:.2f}%"
                                logger_setup.log_strategy(msg)
                                notifier.send_telegram_message(f"<b>{msg}</b>")
                        
                        # --- LOW BALANCE ALERT ---
                        if self.is_live_trading:
                            available_quote = self.get_balance(self.quote_asset)
                            if available_quote < 15.0: # Minimum to place a profitable trade after fees
                                notifier.send_telegram_message(
                                    f"⚠️ <b>LOW BALANCE WARNING ({self.symbol})</b>\n"
                                    f"Available {self.quote_asset}: ${available_quote:.2f}\n"
                                    f"Please add funds to ensure bot can execute next trade."
                                )
                        
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
                            
                        # FETCH SENTIMENT (Fear & Greed)
                        if self.dynamic_settings:
                             self.fear_greed_index = self.fetch_fear_and_greed()
                        
                        # DYNAMIC SETTINGS LOGIC
                        if self.dynamic_settings and self.last_volatility is not None:
                            vol = self.last_volatility
                            vol_percent = vol * 100
                            
                            # FORMULA BASED (Retuned for tighter profit banking)
                            # SL = ~2.0x Vol (was 2.0) - Cap at 8%
                            # Using 8% cap (was 6%) to allow room for high-volatility regime swings.
                            new_sl_percent = min(8.0, max(1.5, vol_percent * 2.0))
                            
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
                            vol_multiplier = 1.2 # Default
                            
                            if self.fear_greed_index is not None:
                                fg_val = self.fear_greed_index
                                if fg_val <= 25:
                                    new_rsi -= 8  # Wait for DEEPER dip in extreme fear
                                    vol_multiplier = 1.5 # Require massive volume to confirm bottom
                                    fg_msg = " (-8 Extreme Fear, 1.5x Vol)"
                                elif fg_val <= 40:
                                    new_rsi -= 3  # Wait for slightly deeper dip
                                    vol_multiplier = 1.3
                                    fg_msg = " (-3 Fear, 1.3x Vol)"
                                elif fg_val >= 75:
                                    new_rsi -= 5
                                    fg_msg = " (-5 Extreme Greed)"
                                elif fg_val >= 60:
                                    new_rsi -= 2
                                    fg_msg = " (-2 Greed)"
                                
                                # Apply Dynamic Volume Multiplier if enabled
                                if self.strategy.volume_confirmation_enabled:
                                    self.strategy.volume_multiplier = vol_multiplier

                                # Clamp final RSI to safe bounds (25-60)
                                new_rsi = max(25, min(60, new_rsi))

                            
                            # Convert back to decimal for Python logic
                            self.strategy.rsi_threshold_buy = new_rsi
                            self.strategy.stop_loss_percent = new_sl_percent / 100.0
                            self.strategy.fixed_stop_loss_percent = new_sl_percent / 100.0
                            # Note: Strategy uses sell_percent as trail distance
                            self.strategy.sell_percent = new_trail_percent / 100.0 
                            
                            current_rsi_val = indicators.calculate_rsi(self.strategy.price_history) if len(self.strategy.price_history) > 14 else 0
                            
                            # Log only if changed significantly or long time passed
                            # Check if we stored previous params to compare? 
                            # For now, simplifying the message as requested to make it readable.
                            
                            sell_context = ""
                            if self.bought_price:
                                peak = self.strategy.peak_price_since_buy or self.bought_price
                                new_trail_price = peak * (1 - (new_trail_percent / 100.0))
                                break_even = self.bought_price * (1 + 2 * self.strategy.trading_fee_percentage)
                                # Concise Sell Context
                                sell_context = f" | Trail Sell < ${new_trail_price:.2f}"

                            # Simplified Log Format
                            msg = f"🔄 TUNING: Vol {vol:.2%} -> RSI Buy < {new_rsi}{fg_msg} | SL {new_sl_percent:.1f}% | Trail {new_trail_percent:.1f}%{sell_context}"
                            
                            # Only log if Volatility changed significantly (>0.5%) OR significant time passed (15 mins)
                            # to reduce spam as requested by user.
                            current_time = time.time()
                            last_log_time = getattr(self, 'last_tuning_log_time', 0)
                            
                            should_log = False
                            vol_change = abs(getattr(self, 'last_vol_logged', 0) - vol)
                            
                            if current_time - last_log_time > 900: # 15 minutes
                                should_log = True
                            elif vol_change > 0.005: # > 0.5% change
                                should_log = True
                                
                            if should_log:
                                self.last_vol_logged = vol
                                self.last_tuning_log_time = current_time
                                self.logger.debug(msg) 
                                logger_setup.log_strategy(msg)
                                pass
                        
                        self.last_volatility_check_time = datetime.datetime.now()
                        
                        # NEW: Fetch higher timeframe trend every volatility check (~10 min)
                        if self.strategy.multi_timeframe_enabled:
                            self.fetch_higher_timeframe_trend()
                            
                        # NEW: Update Support/Resistance (Imp 6)
                        if config.SUPPORT_RESISTANCE_CHECK_ENABLED:
                            self.update_support_resistance()
                    
                    # --- EXECUTE STRATEGY ---
                    current_price = self.check_price()
                    if current_price is not None:
                         # 1. Update Data
                         self.strategy.update_data(current_price)
                         
                         # NEW: Fetch and update volume data periodically
                         current_volume = None
                         if self.strategy.volume_confirmation_enabled:
                             current_volume = self.fetch_current_volume()
                             if current_volume:
                                 self.strategy.update_volume(current_volume)
                         
                         # Warmup Check (5 mins) to stabilize RSI
                         if (time.time() - getattr(self, 'start_time', 0)) < 300:
                             # Optionally log debug but don't spam
                             time.sleep(1)
                             continue
                         
                         # 2. Check Signals (SKIP IF PAUSED)
                         if self.paused:
                             # Still update data, just don't trade
                             self.last_price = current_price
                             time.sleep(1)
                             continue
                         
                         if self.bought_price is None:
                              # Buy Check (now with volume parameter)
                              if self.strategy.check_buy_signal(current_price, self.last_price, current_volume):
                                   # Final Check: Order Book (Imp 5)
                                   if self.check_order_book():
                                       # Dynamic Position Sizing (Risk Parity)
                                       sl_price = current_price * (1 - self.strategy.fixed_stop_loss_percent)
                                       invest_qty = self.calculate_position_size(current_price, sl_price)
                                       
                                       # Fallback if calc fails or return low
                                       if invest_qty == 0:
                                           invest_qty = (self.get_balance(self.quote_asset) * self.position_size_percent) / current_price
                                       
                                       invest_amount = invest_qty * current_price
                                       self.buy(current_price, invest_amount)
                                   else:
                                       # Logged in check_order_book
                                       if config.MISSED_TRADE_LOG_ENABLED:
                                           logger_setup.log_strategy(f"📉 MISSED TRADE: Order Book Unsafe | Price: ${current_price:.2f}")
                         else:
                               # DCA Check (Sniper Mode)
                              dca_triggered = False
                              if self.dca_count < self.strategy.dca_max_levels:
                                  # Cooldown Check (Prevent Spam Loops)
                                  last_attempt = getattr(self, 'last_dca_attempt', 0)
                                  if (time.time() - last_attempt) < 60:
                                      pass # Wait for cooldown
                                  elif self.strategy.check_dca_signal(current_price, self.bought_price):
                                      # Calc trigger details for log
                                      dca_rsi = indicators.calculate_rsi(self.strategy.price_history) if len(self.price_history) > 14 else 0
                                      drop_pct = ((self.bought_price - current_price) / self.bought_price) * 100
                                      
                                      # RECURSIVE MULTIPLIER (Phase 3)
                                      multiplier = self.strategy.dca_multiplier ** self.dca_count
                                      invest_amount = (self.quote_balance * self.position_size_percent) * multiplier
                                      
                                      # Fund safety
                                      available = self.get_balance(self.quote_asset)
                                      if invest_amount > available * 0.98:
                                          invest_amount = available * 0.98
                                      
                                      if invest_amount > 10: 
                                           self.logger.info(f"🛡️ Recursive DCA! Level {self.dca_count+1}/{self.strategy.dca_max_levels} (Mult: {multiplier:.2f}x)")
                                           logger_setup.log_strategy(f"🛡️ DEFENSE TRIGGER: Price -{drop_pct:.2f}% | Level {self.dca_count+1} | RSI {dca_rsi:.1f} < {self.strategy.dca_rsi_threshold}")
                                           self.buy(current_price, invest_amount, is_dca=True)
                                           dca_triggered = True
                                      else:
                                           self.logger.warning(f"DCA Ignored: Amount ${invest_amount:.2f} too low or no funds.")

                              if not dca_triggered:
                                  # UPDATE UI REAL-TIME STATUS (Trail/SL)
                                  if self.bought_price:
                                      u_peak = self.strategy.peak_price_since_buy or current_price
                                      u_trail = u_peak * (1 - self.strategy.sell_percent)
                                      u_sl = self.bought_price * (1 - self.strategy.fixed_stop_loss_percent)
                                      
                                      if self.strategy.sell_percent < 1:
                                           u_target = self.bought_price / (1 - self.strategy.sell_percent)
                                      else:
                                           u_target = 0
                                           
                                      self.current_trail_price = u_trail
                                      self.current_hard_stop = u_sl
                                      self.lock_profit_price = u_target
                                  
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
                    
                    time.sleep(1) # React faster (Safe: Weight 1x60 = 60/1200)
            else:
                self.test()
                # self.running = False handled in finally
        except Exception as e:
            self.logger.exception(f"An error occurred in run: {e}")
            notifier.send_telegram_message(f"⚠️ <b>CRITICAL ERROR</b>\nBot Crashed: {str(e)}")
            # self.stop() # handled in finally
        except KeyboardInterrupt:
            self.shutdown_bot()
        finally:
            self.running = False
            self.logger.info("Bot execution loop ended. Status set to Stopped.")

    def test(self):
        try:
            historical_data = pd.read_csv(self.filename)
            historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp'])

            # Pre-calculate Volatility for dynamic settings backtesting
            # Use 24h window (assuming 15m default i.e. 96 periods) or fallback to 50
            # rolling std / rolling mean
            vol_window = 96
            historical_data['RollingVol'] = historical_data['Price'].rolling(window=vol_window).std() / historical_data['Price'].rolling(window=vol_window).mean()
            
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
            self.equity_history = []
            self.trade_journal.clear()

            
            # Detect Asset from Filename
            fname = os.path.basename(self.filename).lower()
            if 'btc' in fname: self.base_asset = 'BTC'; self.symbol = 'BTCUSDT'
            elif 'sol' in fname: self.base_asset = 'SOL'; self.symbol = 'SOLUSDT'
            elif 'bnb' in fname: self.base_asset = 'BNB'; self.symbol = 'BNBUSDT'
            elif 'xrp' in fname: self.base_asset = 'XRP'; self.symbol = 'XRPUSDT'
            elif 'zec' in fname: self.base_asset = 'ZEC'; self.symbol = 'ZECUSDT'
            else: self.base_asset = 'ETH'; self.symbol = 'ETHUSDT'
            
            
            self.last_price = None
            
            # Initial Volatility
            if self.is_live_trading:
                self.last_volatility = self.calculate_volatility()
                msg_vol = f"__init__: Initial Volatility Calculated: {self.last_volatility}"
                self.logger.debug(msg_vol) # Hide from System
                logger_setup.log_strategy(msg_vol) # Show in Strategy
            else:
                 # Set default for backtest start (will be updated by loop)
                 self.last_volatility = 0.02
            
            self.strategy.set_volatility(self.last_volatility)
            
            if self.last_volatility is None and self.is_live_trading:
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
                
                # Update Volatility from Historical Data
                if 'RollingVol' in row and not pd.isna(row['RollingVol']):
                    self.last_volatility = row['RollingVol']
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
                current_volume = row.get('Volume')
                self.strategy.update_data(current_price)
                if current_volume is not None:
                    self.strategy.update_volume(current_volume)
                
                if self.bought_price is None:
                     if self.strategy.check_buy_signal(current_price, self.last_price, current_volume):
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
                               logger_setup.log_trade(self.logger, self.trade_logger, "Buy", execution_price, quantity, quantity * execution_price, is_test=True)
                               # Backtest Fee
                               self.total_fees += (quantity * execution_price * self.trading_fee_percentage)
                else:
                     # UPDATE BACKTEST UI STATUS
                     u_peak = self.strategy.peak_price_since_buy or current_price
                     self.current_trail_price = u_peak * (1 - self.strategy.sell_percent)
                     self.current_hard_stop = self.bought_price * (1 - self.strategy.fixed_stop_loss_percent)

                     action = self.strategy.check_sell_signal(current_price, self.bought_price)
                     if action in ['SELL', 'STOP_LOSS']:
                          # APPLY SLIPPAGE (Sell Lower)
                          execution_price = current_price * (1 - self.slippage)
                          
                          qty_sold = self.base_balance
                          revenue = self.base_balance * execution_price * (1 - self.trading_fee_percentage)
                          profit_amount = revenue - (self.base_balance * self.bought_price)
                          profit_percent = ((execution_price - self.bought_price) / self.bought_price) * 100
                          
                          self.quote_balance += revenue
                          self.base_balance = 0
                          
                          # Backtest Fee
                          self.total_fees += (revenue * self.trading_fee_percentage)
                          
                          # Metrics Update via Helper
                          self.update_metrics(profit_amount, self.quote_balance)
                          
                          reason = "Sell" if action == 'SELL' else "Stop-loss Sell"
                          
                          # Add to internal journal for Backtest Dashboard
                          j_entry = {
                              'timestamp': row['Timestamp'].isoformat() if hasattr(row['Timestamp'], 'isoformat') else str(row['Timestamp']),
                              'action': 'SELL',
                              'symbol': self.symbol,
                              'price': execution_price,
                              'qty': qty_sold,
                              'total_value': revenue, # Total Exit Value
                              'entry_value': self.bought_price * qty_sold if self.bought_price else 0, # Total Entry Cost
                              'pnl_amount': round(profit_amount, 2),
                              'pnl_percent': round(profit_percent, 2),
                              'balance_after': self.quote_balance,
                              'exit_reason': reason
                          }
                          self.trade_journal.appendleft(j_entry)
                          
                          logger_setup.log_trade(self.logger, self.trade_logger, reason, execution_price, qty_sold, revenue, profit_percent, is_test=True)

                          
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
            self.logger.exception(f"Fatal error in bot {self.symbol}: {e}")
            if self.is_live_trading or self.filename is None:
                notifier.send_telegram_message(f"🚨 <b>CRITICAL SPOT ERROR ({self.symbol})</b>\nBot crashed unexpectedly: {e}")
            self.finished_data = True
