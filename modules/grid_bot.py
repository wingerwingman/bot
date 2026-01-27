"""
Grid Trading Bot Module
Runs alongside the Signal Bot with separate capital allocation.
Places limit orders at fixed price intervals to profit from sideways markets.
"""

import time
import re
import threading
import logging
import json
import os
import datetime
from binance import Client, BinanceAPIException
from . import config
from . import logger_setup
from . import indicators
from . import notifier
from .market_data_manager import market_data_manager


class GridBot:
    """
    Grid Trading Bot that places buy/sell orders at fixed price intervals.
    
    Strategy:
    - Define a price range (lower_bound to upper_bound)
    - Split into N grid levels
    - Place BUY limit orders below current price
    - Place SELL limit orders above current price
    - As orders fill, replace them on the opposite side
    """
    
    def __init__(self, 
                 symbol='ETHUSDT',
                 lower_bound=2800,
                 upper_bound=3200,
                 grid_count=10,
                 capital=1000,
                 is_live=False,
                 resume_state=True,
                 auto_rebalance_enabled=True,
                 volatility_spacing_enabled=False):
        
        self.symbol = symbol
        self.lower_bound = float(lower_bound)
        self.upper_bound = float(upper_bound)
        self.grid_count = int(grid_count)
        self.capital = float(capital)
        self.is_live = is_live
        
        # State
        self.running = False
        self.thread = None
        self.active_orders = []  # List of {order_id, price, side, status}
        self.filled_orders = []
        self.total_profit = 0.0
        self.total_fees = 0.0  # Track fees separately
        self.fee_rate = 0.001  # 0.1% per trade (0.2% round-trip)
        self.buy_fills = 0
        self.sell_fills = 0
        
        # Health & Reliability (Phase 2)
        self.last_active_timestamp = time.time()
        self.ban_until = None
        self.paused = False # NEW: Pause state
        self.auto_rebalance_enabled = auto_rebalance_enabled # Use arg
        self.volatility_spacing_enabled = volatility_spacing_enabled # Use arg
        
        # Store for overrides (to prevent load_state from overwriting NEW settings)
        self._arg_lower_bound = float(lower_bound)
        self._arg_upper_bound = float(upper_bound)
        self._arg_grid_count = int(grid_count)
        self._arg_capital = float(capital)
        self._arg_auto_rebalance = auto_rebalance_enabled
        self._arg_vol_spacing = volatility_spacing_enabled
        
        self.rebalance_count = 0 
        
        # Logger
        self.logger = logging.getLogger("GridBot")
        
        # Binance Client
        self.client = Client(config.API_KEY, config.API_SECRET, tld='us')
        
        # Precision
        self.tick_size = 0.01
        self.step_size = 0.0001
        self._fetch_precision()
        
        # State file
        self.state_file = f"data/grid_state_{symbol}.json"
        self.resume_state = resume_state
        
        # Load saved state if resume enabled
        if self.resume_state:
            self._load_state()
            
        # Start MarketData stream for this symbol
        market_data_manager.start_symbol(self.symbol)
    
    def _save_state(self):
        """Save Grid Bot state to Database (SQLAlchemy)."""
        try:
            from .database import db_session
            from .models import GridState
            
            session = db_session()
            
            grid_state = session.query(GridState).filter_by(symbol=self.symbol).first()
            if not grid_state:
                grid_state = GridState(symbol=self.symbol)
                session.add(grid_state)
            
            grid_state.is_active = self.running
            grid_state.lower_bound = self.lower_bound
            grid_state.upper_bound = self.upper_bound
            grid_state.grid_count = self.grid_count
            grid_state.total_profit = self.total_profit
            grid_state.buy_fills = self.buy_fills
            grid_state.sell_fills = self.sell_fills
            grid_state.active_orders = self.active_orders # JSON list
            
            # Serialize Configuration
            grid_state.configuration = {
                'capital': self.capital,
                'auto_rebalance_enabled': self.auto_rebalance_enabled,
                'volatility_spacing_enabled': self.volatility_spacing_enabled,
                'paused': self.paused,
            }
            
            # Serialize Metrics
            grid_state.metrics = {
                'total_fees': self.total_fees,
                'rebalance_count': self.rebalance_count,
                'filled_orders': self.filled_orders[-100:] # Keep last 100 in DB
            }
            
            session.commit()
            session.close()
            
        except Exception as e:
            self.logger.error(f"Error saving grid state to DB: {e}")
    
    def _load_state(self):
        """Load Grid Bot state from Database (SQLAlchemy)."""
        try:
            from .database import db_session
            from .models import GridState
            
            session = db_session()
            state = session.query(GridState).filter_by(symbol=self.symbol).first()
            
            if state:
                # Basic Fields
                self.lower_bound = state.lower_bound
                self.upper_bound = state.upper_bound
                self.grid_count = state.grid_count
                self.total_profit = state.total_profit or 0.0
                self.buy_fills = state.buy_fills or 0
                self.sell_fills = state.sell_fills or 0
                self.active_orders = state.active_orders or []
                
                # Configuration
                config = state.configuration or {}
                self.capital = config.get('capital', self.capital)
                self.paused = config.get('paused', False)
                self.auto_rebalance_enabled = config.get('auto_rebalance_enabled', True)
                self.volatility_spacing_enabled = config.get('volatility_spacing_enabled', False)
                
                # Metrics
                metrics = state.metrics or {}
                self.total_fees = metrics.get('total_fees', 0.0)
                self.rebalance_count = metrics.get('rebalance_count', 0)
                self.filled_orders = metrics.get('filled_orders', [])
                
                # APPLY OVERRIDES (Startup settings take precedence over DB)
                self.lower_bound = self._arg_lower_bound
                self.upper_bound = self._arg_upper_bound
                self.grid_count = self._arg_grid_count
                self.capital = self._arg_capital
                self.auto_rebalance_enabled = self._arg_auto_rebalance
                self.volatility_spacing_enabled = self._arg_vol_spacing
                
                self.logger.info(f"♻️ Grid state restored from DB: {self.buy_fills} buys, {self.sell_fills} sells, ${self.total_profit:.2f} net profit (fees: ${self.total_fees:.2f})")
                
            session.close()
            
        except Exception as e:
            self.logger.error(f"Error loading grid state from DB: {e}")
    
    def clear_state(self):
        """Clear saved state and reset counters."""
        self.active_orders = []
        self.filled_orders = []
        self.total_profit = 0.0
        self.buy_fills = 0
        self.sell_fills = 0
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        self.logger.info("Grid state cleared.")
    
    def _fetch_precision(self):
        """Fetch symbol precision from exchange."""
        try:
            info = self.client.get_symbol_info(self.symbol)
            for f in info['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    self.tick_size = float(f['tickSize'])
                elif f['filterType'] == 'LOT_SIZE':
                    self.step_size = float(f['stepSize'])
        except Exception as e:
            self.logger.error(f"Error fetching precision: {e}")
        
        # Calculate decimal places from tick/step sizes
        self.price_decimals = len(str(self.tick_size).split('.')[-1].rstrip('0')) if '.' in str(self.tick_size) else 0
        self.qty_decimals = len(str(self.step_size).split('.')[-1].rstrip('0')) if '.' in str(self.step_size) else 0
    
    def round_price(self, price):
        """Round price to tick size and format properly."""
        from decimal import Decimal, ROUND_DOWN
        tick = Decimal(str(self.tick_size))
        p = Decimal(str(price))
        rounded = float((p / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick)
        return round(rounded, self.price_decimals)
    
    def round_qty(self, qty):
        """Round quantity DOWN to step size."""
        from decimal import Decimal, ROUND_DOWN
        step = Decimal(str(self.step_size))
        q = Decimal(str(qty))
        rounded = float((q / step).quantize(Decimal('1'), rounding=ROUND_DOWN) * step)
        return round(rounded, self.qty_decimals)
    
    def calculate_grid_levels(self):
        """
        Calculate price levels for the grid.
        Returns list of prices from lower to upper bound.
        """
        step = (self.upper_bound - self.lower_bound) / self.grid_count
        levels = []
        for i in range(self.grid_count + 1):
            price = self.lower_bound + (step * i)
            levels.append(self.round_price(price))
        return levels
    
    def calculate_order_size(self):
        """Calculate order size per grid level (even split)."""
        # Capital / number of buy levels (below current price)
        # Approximate: half the levels are buys
        buy_levels = self.grid_count // 2
        if buy_levels == 0:
            buy_levels = 1
        
        size_per_level = self.capital / buy_levels
        return size_per_level
    
    def get_current_price(self):
        """Fetch latest price from MarketDataManager (WebSocket / Cached REST)."""
        self.last_active_timestamp = time.time()
        try:
            return market_data_manager.get_price(self.symbol)
        except Exception as e:
            self.logger.error(f"Error fetching current price: {e}")
            return None
    
    def place_grid_orders(self):
        """
        Place initial grid orders.
        BUY orders below current price, SELL orders above.
        """
        current_price = self.get_current_price()
        if current_price is None:
            self.logger.error("Cannot place orders: No price available")
            return
        
        levels = self.calculate_grid_levels()
        
        # In LIVE mode, fetch actual USDT balance for buy orders
        available_usdt = self.capital  # Default to config capital
        available_base = 0.0  # For sell orders
        
        if self.is_live:
            try:
                account = self.client.get_account()
                usdt_locked = 0.0
                base_locked = 0.0
                for b in account['balances']:
                    if b['asset'] == 'USDT':
                        available_usdt = float(b['free'])
                        usdt_locked = float(b['locked'])
                    elif b['asset'] == self.symbol.replace('USDT', ''):
                        available_base = float(b['free'])
                        base_locked = float(b['locked'])
                
                self.logger.info(f"💰 USDT: ${available_usdt:.2f} free, ${usdt_locked:.2f} locked | {self.symbol.replace('USDT', '')}: {available_base:.6f} free, {base_locked:.6f} locked")
                
                # STRICT SEPARATION: Check if Spot Bot is holding funds and reserve them
                # Must be done BEFORE Capital Logic to correctly value Grid Inventory
                try:
                    spot_state_file = f"data/state_live_{self.symbol}.json"
                    
                    if os.path.exists(spot_state_file):
                        with open(spot_state_file, 'r') as f:
                            spot_state = json.load(f)
                        
                        spot_holdings = float(spot_state.get('base_balance_at_buy') or spot_state.get('base_balance', 0.0))
                        
                        # Only subtract if the Spot Bot is actually holding a position (bought entry)
                        if spot_state.get('bought_price'):
                            available_base -= spot_holdings
                            if available_base < 0: available_base = 0 
                            self.logger.info(f"🛑 Reserved {spot_holdings:.6f} {self.symbol.replace('USDT', '')} for Spot Bot. Available for Grid: {available_base:.6f}")
                except Exception as e:
                    self.logger.warning(f"Failed to check Spot Bot reservations: {e}")

                # LIMIT CAPITAL USAGE: Respect the slider allocation + Reinvest Net Profit
                # Include existing Grid Inventory (ETH) in the logic to prevent over-allocation.
                allowable_capital = self.capital + self.total_profit
                if allowable_capital < 0: allowable_capital = 0 

                # Value of current Grid ETH holdings (Free + Locked - Spot Reservation)
                # We calculate Total Grid Base by adding Locked funds (active orders) to the Available (Free - Spot)
                # Note: 'available_base' at this point is (Free - Spot). 
                # We assume Spot Holdings are NOT in Locked Orders (if they are 'Waiting for Sell', they are free).
                
                total_grid_base = available_base
                if 'base_locked' in locals():
                     total_grid_base += base_locked
                
                base_equity = total_grid_base * current_price
                
                # Remaining USDT alloc = Total Cap - ETH Value
                adjusted_usdt_cap = allowable_capital - base_equity
                if adjusted_usdt_cap < 0: adjusted_usdt_cap = 0

                if available_usdt > adjusted_usdt_cap:
                    self.logger.info(f"🔒 Capital Safety: Target ${allowable_capital:.2f} | Held Inv: ${base_equity:.2f} | Max Used USDT: ${adjusted_usdt_cap:.2f}")
                    available_usdt = adjusted_usdt_cap
                    
            except Exception as e:
                self.logger.error(f"Error fetching balance: {e}")
        
        # Count buy/sell levels
        buy_levels = [p for p in levels if p < current_price * 0.995]
        sell_levels = [p for p in levels if p > current_price * 1.005]
        
        # SMART LEVEL REDUCTION: Ensure each order is profitable after fees
        # Minimum order value to cover ~$0.50 fee threshold and be meaningful
        min_profitable_order = 15.0  # $15 min to make profit after 0.2% round-trip fees
        
        # Reduce buy levels if each order would be too small
        while len(buy_levels) > 0 and (available_usdt / len(buy_levels)) < min_profitable_order:
            buy_levels = buy_levels[1:]  # Remove lowest buy level
            self.logger.info(f"⚠️ Reduced buy levels to {len(buy_levels)} for profitability")
        
        # Calculate order sizes based on available capital
        buy_order_value = available_usdt / len(buy_levels) if buy_levels else 0
        sell_order_qty = available_base / len(sell_levels) if sell_levels else 0
        
        if len(buy_levels) == 0:
            self.logger.warning("⚠️ No buy levels placed - insufficient USDT for profitable grid")
        if len(sell_levels) == 0 and available_base < 0.0001:
            self.logger.warning("⚠️ No sell levels placed - no base asset holdings")
        
        self.logger.info(f"Grid: {len(buy_levels)} BUY levels (${buy_order_value:.2f} each), {len(sell_levels)} SELL levels ({sell_order_qty:.6f} each)")
        
        for price in levels:
            if price < current_price * 0.995:  # Buy levels (with buffer)
                side = 'BUY'
                if buy_order_value < 10:
                    self.logger.warning(f"Skipping BUY @ {price:.2f}: Insufficient USDT (${available_usdt:.2f} total)")
                    continue
                qty = buy_order_value / price
            elif price > current_price * 1.005:  # Sell levels (with buffer)
                side = 'SELL'
                if sell_order_qty < 0.0001:  # Min ETH qty
                    self.logger.warning(f"Skipping SELL @ {price:.2f}: Insufficient base asset ({available_base:.6f})")
                    continue
                qty = sell_order_qty
            else:
                continue  # Skip levels too close to current price
            
            qty = self.round_qty(qty)
            
            # Skip if order value is below minimum ($10)
            actual_order_value = qty * price
            if actual_order_value < 10.0:
                self.logger.warning(f"Skipping {side} @ {price:.2f}: Order value ${actual_order_value:.2f} below minimum $10")
                continue
            
            if self.is_live:
                try:
                    order = self.client.create_order(
                        symbol=self.symbol,
                        side=side,
                        type=Client.ORDER_TYPE_LIMIT,
                        timeInForce=Client.TIME_IN_FORCE_GTC,
                        quantity=qty,
                        price=str(self.round_price(price))
                    )
                    self.active_orders.append({
                        'order_id': order['orderId'],
                        'price': price,
                        'side': side,
                        'qty': qty,
                        'status': 'OPEN'
                    })
                    self.logger.info(f"Placed {side} @ {price:.2f} qty={qty:.6f}")
                except Exception as e:
                    self.logger.error(f"Error placing {side} @ {price}: {e}")
            else:
                # Simulated order
                self.active_orders.append({
                    'order_id': f"SIM_{side}_{price}",
                    'price': price,
                    'side': side,
                    'qty': qty,
                    'status': 'OPEN'
                })
                self.logger.info(f"[SIM] Placed {side} @ {price:.2f} qty={qty:.6f}")
    
    def check_order_fills(self):
        """
        Check if any orders have been filled.
        In live mode, query Binance.
        In sim mode, check if price touched order level.
        """
        current_price = self.get_current_price()
        if current_price is None:
            return
        
        # --- DYNAMIC GRID REBALANCING ---
        # If enabled, checking if price is outside bounds then re-center grid
        if self.running and self.auto_rebalance_enabled:
            # Check for breakout (buffer of 0.5% outside range)
            buffer = 0.005
            is_below = current_price < self.lower_bound * (1 - buffer)
            is_above = current_price > self.upper_bound * (1 + buffer)
            
            if is_below or is_above:
                self.logger.info(f"Dynamic Rebalance Triggered: Price {current_price:.2f} out of bounds ({self.lower_bound}-{self.upper_bound})")
                
                # Check for Volatility-Based Spacing
                if self.volatility_spacing_enabled:
                    # Recalculate range width and levels based on current volatility
                    res = calculate_auto_range(self.symbol, use_volatility=True, capital=self.capital)
                    if res:
                        new_lower = res['lower_bound']
                        new_upper = res['upper_bound']
                        new_levels = res['recommended_levels']
                        vol_pct = res.get('volatility_percent', 0)
                        
                        self.logger.info(f"Volatility Rebalance ({vol_pct:.1f}% Vol): Adjusting range to ±{res['range_percent']}% and {new_levels} levels. New range: {new_lower:.2f} - {new_upper:.2f}")
                        
                        self.update_config(lower_bound=new_lower, upper_bound=new_upper, grid_count=new_levels)
                        self.rebalance_count += 1
                        return

                # Standard Rebalance: Keep same spread width, just center it
                curr_spread_pct = (self.upper_bound - self.lower_bound) / self.lower_bound
                half_spread = curr_spread_pct / 2
                
                new_lower = current_price * (1 - half_spread)
                new_upper = current_price * (1 + half_spread)
                
                # Apply new configuration
                self.logger.info(f"Re-centering grid to {new_lower:.2f} - {new_upper:.2f}")
                self.update_config(lower_bound=new_lower, upper_bound=new_upper)
                self.rebalance_count += 1
                
                # Return early to let next cycle handle new orders
                return

        for order in self.active_orders[:]:  # Copy list to allow modification
            if order['status'] != 'OPEN':
                continue
            
            filled = False
            
            if self.is_live:
                try:
                    status = self.client.get_order(
                        symbol=self.symbol,
                        orderId=order['order_id']
                    )
                    if status['status'] == 'FILLED':
                        filled = True
                except Exception as e:
                    self.logger.error(f"Error checking order: {e}")
            else:
                # Simulation: check if price crossed order level
                if order['side'] == 'BUY' and current_price <= order['price']:
                    filled = True
                elif order['side'] == 'SELL' and current_price >= order['price']:
                    filled = True
            
            if filled:
                order['status'] = 'FILLED'
                if len(self.filled_orders) > 100:
                    self.filled_orders.pop(0) # Remove oldest
                self.filled_orders.append(order)
                self.active_orders.remove(order)
                
                if order['side'] == 'BUY':
                    self.buy_fills += 1
                    self.logger.info(f"BUY FILLED @ {order['price']:.2f}")
                else:
                    self.sell_fills += 1
                    self.logger.info(f"SELL FILLED @ {order['price']:.2f}")
                
                # Calculate Fees (Real vs Estimate)
                trade_value = order['qty'] * order['price']
                real_fee = self._fetch_real_fee(order['order_id'])
                fee = real_fee if real_fee is not None else (trade_value * self.fee_rate)
                self.total_fees += fee
                
                # Realized Profit logic: Only realized when a SELL fills (assuming we bought lower)
                # For simplicity in grid: profit = distance between levels * qty
                net_profit = 0.0
                grid_step = (self.upper_bound - self.lower_bound) / self.grid_count
                
                if order['side'] == 'SELL':
                    # Realized Gross = Spread * Qty
                    # Realized Net = (Spread * Qty) - (Buy Fee + Sell Fee)
                    # We estimate Buy Fee to be same as Sell Fee for simplicity if not tracked per-cycle
                    cycle_fees = fee * 2 
                    net_profit = (order['qty'] * grid_step) - cycle_fees
                    self.total_profit += net_profit
                
                # --- LOG TO JOURNAL ---
                try:
                    j_entry = {
                        'action': order['side'],
                        'symbol': self.symbol,
                        'price': float(order['price']),
                        'qty': float(order['qty']),
                        'total_value': float(order['price']) * float(order['qty']),
                        'entry_reason': "Grid Level",
                        'timestamp': datetime.datetime.now().isoformat(),
                        'fee': float(fee),
                        'pnl_amount': float(net_profit), # Only non-zero on SELL
                        'pnl_percent': float((grid_step/order['price'])*100) if order['side'] == 'SELL' else 0.0,
                        'balance_after': 0.0
                    }
                    logger_setup.log_trade_journal(j_entry)
                except Exception as ex:
                    self.logger.error(f"Journal Log Error: {ex}")
                # ----------------------
                
                if order['side'] == 'SELL':
                    self.logger.info(f"  → Cycle Net Profit: ${net_profit:.2f} (includes est. buy fee)")
                    
                    # --- SYNC WITH CAPITAL MANAGER ---
                    try:
                        # Record 'grid' bot ID profit
                        # We use 'grid' to aggregate all grid bots into the capital panel's "Grid" slot
                        # True = Win (Grid sells are always wins by definition of the strategy)
                        from .capital_manager import capital_manager
                        capital_manager.record_trade('grid', net_profit, True)
                    except Exception as e:
                        self.logger.error(f"Capital Manager Sync Error: {e}")
                
                # TUNING METRICS: Log context for analysis
                current_vol = self.volatility if hasattr(self, 'volatility') else "N/A"
                vol_display = f"{current_vol*100:.2f}%" if isinstance(current_vol, float) else "N/A"
                grid_step_pct = (grid_step / order['price']) * 100
                
                self.logger.info(f"  → Context: Vol={vol_display} | Range=${self.lower_bound}-${self.upper_bound} | Step={grid_step:.2f} ({grid_step_pct:.2f}%)")
                
                # PERSISTENT TUNING LOG (CSV)
                try:
                    logger_setup.log_tuning(
                        symbol=self.symbol,
                        action=order['side'],
                        price=order['price'],
                        qty=order['qty'],
                        profit=net_profit,
                        volatility=current_vol if isinstance(current_vol, float) else 0.0,
                        range_low=self.lower_bound,
                        range_high=self.upper_bound,
                        step=grid_step,
                        step_pct=grid_step_pct
                    )
                except Exception as e:
                    self.logger.error(f"Failed to log tuning metrics: {e}")
                
                # TELEGRAM NOTIFICATION - Enhanced with performance
                try:
                    mode_indicator = "🟢" if self.is_live else "🧪"
                    
                    if order['side'] == 'SELL':
                         notifier.send_telegram_message(
                            f"{mode_indicator} <b>GRID SELL</b>\n"
                            f"Symbol: {self.symbol}\n"
                            f"Price: ${order['price']:.2f}\n"
                            f"Profit: ${net_profit:.2f}\n"
                            f"\n📈 <b>Grid Performance:</b>\n"
                            f"Buys: {self.buy_fills} | Sells: {self.sell_fills}\n"
                            f"Net Profit: ${self.total_profit:.2f}\n"
                            f"Total Fees: ${self.total_fees:.2f}"
                         )
                    else:
                         notifier.send_telegram_message(
                            f"{mode_indicator} <b>GRID BUY</b>\n"
                            f"Symbol: {self.symbol}\n"
                            f"Price: ${order['price']:.2f}\n"
                            f"Qty: {order['qty']:.6f}\n"
                            f"Buy #{self.buy_fills} | Active Orders: {len(self.active_orders)}"
                         )
                except Exception as e:
                    self.logger.error(f"Failed to send Telegram alert: {e}")
                

                
                # REPLENISH GRID (Cycle the order)
                self._place_counter_order(order)
                
                # Save state after each fill
                self._save_state()
    
    def cancel_all_orders(self):
        """Cancel all active grid orders."""
        if self.is_live:
            for order in self.active_orders:
                try:
                    self.client.cancel_order(
                        symbol=self.symbol,
                        orderId=order['order_id']
                    )
                    self.logger.info(f"Cancelled order {order['order_id']}")
                except Exception as e:
                    self.logger.error(f"Error cancelling order: {e}")
        
        self.active_orders.clear()

    def manual_sell(self, reason="Manual Sell"):
        """Cancel all orders and market sell everything currently held by this grid bot."""
        self.logger.info(f"🚨 {reason} triggered. Liquidating Grid Bot...")
        
        # 1. Cancel all limit orders
        self.cancel_all_orders()
        
        # 2. Market sell remaining base asset if live
        if self.is_live:
            try:
                base_asset = self.symbol.replace('USDT', '')
                account = self.client.get_account()
                available_base = 0.0
                for b in account['balances']:
                    if b['asset'] == base_asset:
                        available_base = float(b['free'])
                        break
                
                # Check Spot Bot reservations to avoid selling Spot Bot's coins
                spot_state_file = f"data/state_live_{self.symbol}.json"
                if os.path.exists(spot_state_file):
                    try:
                        with open(spot_state_file, 'r') as f:
                            spot_state = json.load(f)
                        if spot_state.get('bought_price'):
                            spot_holdings = float(spot_state.get('base_balance_at_buy') or spot_state.get('base_balance', 0.0))
                            available_base = max(0.0, available_base - spot_holdings)
                            self.logger.info(f"Reserved {spot_holdings} {base_asset} for Spot Bot. Grid selling {available_base}")
                    except:
                        pass
                
                if available_base > 0:
                    qty = self.round_qty(available_base)
                    # Use a small buffer to avoid "insufficient balance" due to fees or sub-tick amounts
                    if qty > 0:
                        order = self.client.create_order(
                            symbol=self.symbol, 
                            side='SELL', 
                            type='MARKET', 
                            quantity=qty
                        )
                        self.logger.info(f"✅ Market Sell Executed for {qty} {base_asset} (Panic/Manual)")
                        notifier.send_telegram_message(f"🚨 <b>GRID LIQUIDATED ({self.symbol})</b>\nManual sell executed via dashboard.")
            except Exception as e:
                self.logger.error(f"Failed to execute market sell during grid liquidation: {e}")
        
        # 3. Clear memory and persistence
        self.clear_state()
        self.logger.info("Grid Bot state cleared. Bot remains in 'running' state but with no orders.")
    
    def get_status(self):
        """Return current grid status for UI."""
        # Fetch real balances if live
        usdt_balance = 0.0
        base_balance = 0.0
        base_asset = self.symbol.replace('USDT', '')
        
        # Fetch real balances if live (Throttled to prevent API Ban)
        # Weight of get_account is 20. Excessive polling triggers 429.
        current_time = time.time()
        
        if self.is_live:
            # Use MarketDataManager cached account info (Saves weight 20)
            account = market_data_manager.get_account_info()
            if account and 'balances' in account:
                for b in account['balances']:
                    if b['asset'] == 'USDT':
                        usdt_balance = float(b['free']) + float(b['locked'])
                    elif b['asset'] == base_asset:
                        total_balance = float(b['free']) + float(b['locked'])
                        
                        # Subtract Spot Bot held funds if any
                        spot_state_file = f"data/state_live_{self.symbol}.json"
                        if os.path.exists(spot_state_file):
                            try:
                                with open(spot_state_file, 'r') as f:
                                    s = json.load(f)
                                    # Check if spot bot bought anything
                                    if s.get('bought_price'):
                                        spot_holdings = float(s.get('base_balance_at_buy') or s.get('base_balance', 0.0))
                                        total_balance = max(0.0, total_balance - spot_holdings)
                            except:
                                pass
                        
                        base_balance = total_balance
            
            # --- FIX: Show Allocated Balance instead of Total Wallet Balance ---
            # If the bot is running and has active orders, calculate the actual funds locked in the grid.
            if self.running and len(self.active_orders) > 0:
                allocated_usdt = 0.0
                allocated_base = 0.0
                for o in self.active_orders:
                    if o['side'] == 'BUY':
                        allocated_usdt += float(o['price']) * float(o['qty'])
                    elif o['side'] == 'SELL':
                        allocated_base += float(o['qty'])
                
                # Update the displayed balances to reflect only what is allocated to this bot
                if allocated_usdt > 0:
                    usdt_balance = allocated_usdt
                    # Add a small buffer for potential unplaced orders or fees if needed, 
                    # but strictly 'allocated' is safer to show.
                
                if allocated_base > 0:
                    base_balance = allocated_base
        current_price = self.get_current_price() or 0
        
        return {
            'running': self.running,
            'is_live': self.is_live,
            'paused': self.paused,
            'auto_rebalance_enabled': self.auto_rebalance_enabled,
            'volatility_spacing_enabled': self.volatility_spacing_enabled,
            'symbol': self.symbol,
            'lower_bound': self.lower_bound,
            'upper_bound': self.upper_bound,
            'grid_count': self.grid_count,
            'capital': self.capital,
            'active_orders': len(self.active_orders),
            'buy_fills': self.buy_fills,
            'sell_fills': self.sell_fills,
            'total_profit': self.total_profit,
            'total_fees': self.total_fees,
            'current_price': current_price,
            'usdt_balance': usdt_balance,
            'base_balance': base_balance,
            'base_asset': base_asset,
            'base_usd_value': base_balance * current_price,
            'ban_until': self.ban_until,
            'orders': self.active_orders,
            'performance': self.get_performance_summary()
        }
    
    
    def get_performance_summary(self):
        """Return performance metrics for Grid Bot."""
        total_fills = self.buy_fills + self.sell_fills
        win_rate = (self.sell_fills / total_fills * 100) if total_fills > 0 else 0
        
        # Grid bots don't have traditional 'Sharpe' easily without equity history, 
        # so we return a simplified version or N/A
        return {
            "total_trades": total_fills,
            "winning_trades": self.sell_fills,
            "losing_trades": 0, # In grid, we don't usually track 'losing' fills in same way
            "win_rate": round(win_rate, 1),
            "profit_factor": 1.5 if self.total_profit > 0 else 1.0, # Placeholder/Est for UI
            "avg_return": (self.total_profit / self.capital * 100) if self.capital > 0 else 0,
            "max_drawdown": 0, # Not tracked per-grid yet
            "sharpe_ratio": 1.1 if self.total_profit > 0 else 0 # Placeholder
        }

    def _fetch_real_fee(self, order_id):
        """Fetch actual commission paid for an order and convert to USDT."""
        if not self.is_live:
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
                elif asset == self.symbol.replace('USDT',''):
                    trade_price = float(t['price'])
                    total_fee_usdt += fee * trade_price
            
            if len(trades) > 0:
                self.logger.info(f"🧾 Actual Fee Fetched: ${total_fee_usdt:.4f}")
                return total_fee_usdt
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to fetch real fee: {e}")
            return None

    def _place_counter_order(self, filled_order):
        step = (self.upper_bound - self.lower_bound) / self.grid_count
        new_side = 'SELL' if filled_order['side'] == 'BUY' else 'BUY'
        new_price = filled_order['price'] + step if new_side == 'SELL' else filled_order['price'] - step
        new_price = self.round_price(new_price)
        
        # Check bounds
        if new_price > self.upper_bound * 1.01 or new_price < self.lower_bound * 0.99:
           return

        qty = filled_order['qty']
        
        if self.is_live:
            try:
                order = self.client.create_order(
                    symbol=self.symbol,
                    side=new_side,
                    type=Client.ORDER_TYPE_LIMIT,
                    timeInForce=Client.TIME_IN_FORCE_GTC,
                    quantity=qty,
                    price=str(new_price)
                )
                self.active_orders.append({
                    'order_id': order['orderId'],
                    'price': new_price,
                    'side': new_side,
                    'qty': qty,
                    'status': 'OPEN'
                })
                self.logger.info(f"♻️ REPLENISH: Placed {new_side} @ {new_price:.2f}")
            except Exception as e:
                self.logger.error(f"Failed to replenish grid: {e}")
        else:
             # Sim
             self.active_orders.append({
                'order_id': f"SIM_{new_side}_{new_price}",
                'price': new_price,
                'side': new_side,
                'qty': qty,
                'status': 'OPEN'
             })
             self.logger.info(f"♻️ [SIM] REPLENISH: Placed {new_side} @ {new_price:.2f}")

    def run(self):
        """Main grid bot loop."""
        self.logger.info(f"Grid Bot started: {self.symbol} ${self.lower_bound}-${self.upper_bound} x{self.grid_count}")
        
        # Place initial orders
        if self.active_orders:
            self.logger.info(f"♻️ Resuming session with {len(self.active_orders)} active orders loaded from state.")
        else:
            self.place_grid_orders()
            self._save_state()  # Save after placing orders
        
        # Send startup notification
        mode_indicator = "🟢" if self.is_live else "🧪"
        start_msg = (
            f"🤖 <b>GRID BOT STARTED</b>\n"
            f"Symbol: {self.symbol}\n"
            f"Mode: {mode_indicator} {'LIVE' if self.is_live else 'SIMULATION'}\n"
            f"Range: ${self.lower_bound:.2f} - ${self.upper_bound:.2f}\n"
            f"Levels: {self.grid_count}\n"
            f"Capital: ${self.capital:.2f}\n"
            f"Active Orders: {len(self.active_orders)}"
        )
        notifier.send_telegram_message(start_msg)
        
        try:
            while self.running:
                try:
                    # Skip order checks while paused (still running, just not trading)
                    if self.paused:
                        time.sleep(5)
                        continue
                        
                    fills_before = self.buy_fills + self.sell_fills
                    self.check_order_fills()
                    
                    # Save state if any fills occurred
                    if (self.buy_fills + self.sell_fills) > fills_before:
                        self._save_state()
                        
                    time.sleep(5)  # Check every 5 seconds
                except Exception as e:
                    self.logger.error(f"Grid loop error: {e}")
                    time.sleep(10)
                
                # --- LOW BALANCE ALERT (Every ~hour) ---
                last_bal_check = getattr(self, 'last_bal_alert_time', 0)
                if self.is_live and time.time() - last_bal_check > 3600:
                    try:
                        self.last_bal_alert_time = time.time()
                        account = self.client.get_account()
                        for b in account['balances']:
                            if b['asset'] == 'USDT':
                                free_usdt = float(b['free'])
                                if free_usdt < 15.0:
                                    notifier.send_telegram_message(
                                        f"⚠️ <b>LOW BALANCE WARNING (Grid: {self.symbol})</b>\n"
                                        f"Free USDT: ${free_usdt:.2f}\n"
                                        f"Bot may fail to place new buy orders."
                                    )
                                break
                    except:
                        pass
        except Exception as fatal_e:
            if self.running:
                self.logger.critical(f"CRITICAL FATAL ERROR in {self.symbol} Grid Bot: {fatal_e}")
                notifier.send_telegram_message(f"🚨 <b>CRITICAL GRID ERROR ({self.symbol})</b>\nBot crashed unexpectedly: {fatal_e}")
            raise fatal_e
        
        # Cleanup - save final state
        # USER PREFERENCE: Treat Stop as Pause. Do NOT cancel orders.
        # This allows resuming exactly where left off.
        self._save_state()
        # self.cancel_all_orders() # Commented out to enable Pause/Resume behavior
        self.logger.info("Grid Bot paused/stopped. Orders remain active.")
    
    def pause(self):
        """Pause the grid bot - keeps running but stops checking orders."""
        if not self.paused:
            self.paused = True
            self.logger.info("Grid Bot PAUSED")
            # Persist state
            self._save_state()
            if self.is_live:
                notifier.send_telegram_message(f"⏸️ <b>GRID BOT PAUSED</b>\nSymbol: {self.symbol}\nOrders remain active.")
    
    def resume(self):
        """Resume the grid bot after pause."""
        if self.paused:
            self.paused = False
            self.logger.info("Grid Bot RESUMED")
            # Persist state
            self._save_state()
            if self.is_live:
                notifier.send_telegram_message(f"▶️ <b>GRID BOT RESUMED</b>\nSymbol: {self.symbol}")

    def update_config(self, lower_bound=None, upper_bound=None, grid_count=None, capital=None, auto_rebalance_enabled=None, volatility_spacing_enabled=None, resume_state=None):
        """Update bot configuration on the fly."""
        needs_reset = False
        
        if resume_state is not None:
            self.resume_state = bool(resume_state)

        if auto_rebalance_enabled is not None:
            new_val = bool(auto_rebalance_enabled)
            if new_val != self.auto_rebalance_enabled:
                 self.logger.info(f"🔄 Grid Config: Auto-Rebalance set to {new_val}")
            self.auto_rebalance_enabled = new_val
            
        if volatility_spacing_enabled is not None:
            new_val = bool(volatility_spacing_enabled)
            if new_val != self.volatility_spacing_enabled:
                 self.logger.info(f"🔄 Grid Config: Volatility-Based Spacing set to {new_val}")
            self.volatility_spacing_enabled = new_val
        
        if lower_bound is not None and float(lower_bound) != self.lower_bound:
            self.lower_bound = float(lower_bound)
            needs_reset = True
        
        if upper_bound is not None and float(upper_bound) != self.upper_bound:
            self.upper_bound = float(upper_bound)
            needs_reset = True
            
        if grid_count is not None and int(grid_count) != self.grid_count:
            self.grid_count = int(grid_count)
            needs_reset = True

        if capital is not None and float(capital) != self.capital:
            self.capital = float(capital)
            needs_reset = True

        if needs_reset and self.running:
            self.logger.info("Grid Config changed. Resetting grid orders to apply new bounds/levels...")
            self.cancel_all_orders()
            self.place_grid_orders()
            
        self._save_state() # ALWAYS save to ensure toggles like volatility_spacing/auto_rebalance persist
        return True
    
    def start(self):
        """Start the grid bot in a thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.run)
            self.thread.start()
            self.logger.info("Grid Bot thread started.")
    
    def stop(self):
        """Stop the grid bot."""
        self.running = False
        self.logger.info("Grid Bot stopping...")
        
        # Send shutdown notification with final stats
        mode_indicator = "🟢" if self.is_live else "🧪"
        stop_msg = (
            f"🛑 <b>GRID BOT STOPPED</b>\n"
            f"Symbol: {self.symbol}\n"
            f"Mode: {mode_indicator} {'LIVE' if self.is_live else 'SIMULATION'}\n"
            f"\n📊 <b>Final Session Stats:</b>\n"
            f"Buys: {self.buy_fills} | Sells: {self.sell_fills}\n"
            f"Net Profit: ${self.total_profit:.2f}\n"
            f"Total Fees: ${self.total_fees:.2f}"
        )
        notifier.send_telegram_message(stop_msg)


def calculate_auto_range(symbol='ETHUSDT', use_volatility=True, capital=100.0):
    """
    Auto-calculate grid range based on market volatility and available capital.
    
    - Low volatility (<2%): Tighter range (±3%), more levels
    - Medium volatility (2-4%): Normal range (±5%), standard levels
    - High volatility (>4%): Wider range (±8%), fewer levels
    
    Constraints:
    - Minimum order size per level ~$11 (providing buffet over $10 limit)
    - Max levels = Capital / 11
    
    Returns dict with: lower_bound, upper_bound, recommended_levels, volatility
    """
    try:
        client = Client(config.API_KEY, config.API_SECRET, tld='us')
        
        # Get current price
        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])
        
        # Default range
        range_percent = 5
        recommended_levels = 10
        volatility = None
        
        if use_volatility:
            # Fetch klines for ATR calculation
            klines = client.get_klines(symbol=symbol, interval='1h', limit=24)
            volatility = indicators.calculate_volatility_from_klines(klines)
            
            if volatility is not None:
                vol_percent = volatility * 100
                
                # Volatility-based grid sizing
                if vol_percent < 2.0:
                    # Low volatility: Tight range, more levels
                    range_percent = 3
                    recommended_levels = 15
                    logging.info(f"Grid: LOW volatility ({vol_percent:.2f}%) → Tight range ±{range_percent}%, {recommended_levels} levels")
                elif vol_percent > 4.0:
                    # High volatility: Wide range, fewer levels
                    range_percent = 8
                    recommended_levels = 8
                    logging.info(f"Grid: HIGH volatility ({vol_percent:.2f}%) → Wide range ±{range_percent}%, {recommended_levels} levels")
                else:
                    # Medium volatility: Standard settings
                    range_percent = 5
                    recommended_levels = 10
                    logging.info(f"Grid: MEDIUM volatility ({vol_percent:.2f}%) → Normal range ±{range_percent}%, {recommended_levels} levels")
        
        # --- Capital Constraints ---
        # Binance min order is usually $10. We use $11 to be safe.
        min_order_value = 11.0
        max_levels_for_capital = int(capital / min_order_value)
        
        # Ensure we have at least 2 levels if capital allows, else 0/error logic usually handled by UI
        if max_levels_for_capital < 2:
            max_levels_for_capital = 2 # Let it fail on validation if really too low, but don't return 0
            
        # Clamp recommended levels
        if recommended_levels > max_levels_for_capital:
            logging.warning(f"Grid: Clamping levels from {recommended_levels} to {max_levels_for_capital} due to capital constraint (${capital})")
            recommended_levels = max(2, max_levels_for_capital)
        
        # Calculate bounds
        range_amount = current_price * (range_percent / 100)
        lower = current_price - range_amount
        upper = current_price + range_amount
        
        return {
            'lower_bound': round(lower, 2),
            'upper_bound': round(upper, 2),
            'recommended_levels': recommended_levels,
            'volatility': volatility,
            'volatility_percent': (volatility * 100) if volatility else None,
            'range_percent': range_percent,
            'current_price': current_price,
            'max_levels_for_capital': max_levels_for_capital
        }
    
    except Exception as e:
        logging.error(f"Auto-range error: {e}")
        return None

