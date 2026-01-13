"""
Grid Trading Bot Module
Runs alongside the Signal Bot with separate capital allocation.
Places limit orders at fixed price intervals to profit from sideways markets.
"""

import time
import threading
import logging
import json
import os
from binance import Client
from . import config
from . import logger_setup
from . import indicators
from . import notifier


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
                 resume_state=True):
        
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
    
    def _save_state(self):
        """Save Grid Bot state to file."""
        try:
            os.makedirs('data', exist_ok=True)
            state = {
                'symbol': self.symbol,
                'lower_bound': self.lower_bound,
                'upper_bound': self.upper_bound,
                'grid_count': self.grid_count,
                'capital': self.capital,
                'active_orders': self.active_orders,
                'filled_orders': self.filled_orders,
                'total_profit': self.total_profit,
                'total_fees': self.total_fees,
                'buy_fills': self.buy_fills,
                'sell_fills': self.sell_fills,
                'running': self.running
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving grid state: {e}")
    
    def _load_state(self):
        """Load Grid Bot state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                
                # Only restore if same symbol
                if state.get('symbol') == self.symbol:
                    self.active_orders = state.get('active_orders', [])
                    self.filled_orders = state.get('filled_orders', [])
                    self.total_profit = state.get('total_profit', 0.0)
                    self.total_fees = state.get('total_fees', 0.0)
                    self.buy_fills = state.get('buy_fills', 0)
                    self.sell_fills = state.get('sell_fills', 0)
                    self.logger.info(f"♻️ Grid state restored: {self.buy_fills} buys, {self.sell_fills} sells, ${self.total_profit:.2f} net profit (fees: ${self.total_fees:.2f})")
        except Exception as e:
            self.logger.error(f"Error loading grid state: {e}")
    
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
    
    def round_price(self, price):
        """Round price to tick size."""
        return round(price / self.tick_size) * self.tick_size
    
    def round_qty(self, qty):
        """Round quantity to step size."""
        return round(qty / self.step_size) * self.step_size
    
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
        """Get current market price."""
        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"Error getting price: {e}")
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
        order_value = self.calculate_order_size()
        
        self.logger.info(f"Grid Levels: {levels}")
        self.logger.info(f"Order Value per Level: ${order_value:.2f}")
        
        for price in levels:
            if price < current_price * 0.995:  # Buy levels (with buffer)
                side = 'BUY'
                qty = order_value / price
            elif price > current_price * 1.005:  # Sell levels (with buffer)
                side = 'SELL'
                # For sell, we need to already hold the asset
                # In grid trading, we typically start with capital, so sells are placed after buys fill
                # For simplicity, we'll just track virtual sells
                qty = order_value / price
            else:
                continue  # Skip levels too close to current price
            
            qty = self.round_qty(qty)
            
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
                self.filled_orders.append(order)
                self.active_orders.remove(order)
                
                if order['side'] == 'BUY':
                    self.buy_fills += 1
                    self.logger.info(f"BUY FILLED @ {order['price']:.2f}")
                else:
                    self.sell_fills += 1
                    self.logger.info(f"SELL FILLED @ {order['price']:.2f}")
                
                # Calculate profit with fees
                grid_step = (self.upper_bound - self.lower_bound) / self.grid_count
                gross_profit = order['qty'] * grid_step
                
                # Simulate fees (0.1% per trade, both buy and sell)
                trade_value = order['qty'] * order['price']
                fee = trade_value * self.fee_rate
                self.total_fees += fee
                
                # Net profit = gross - fee (we only count half since we need buy+sell for full profit)
                net_profit = gross_profit - (fee * 2)  # Account for both sides
                self.total_profit += net_profit
                
                self.logger.info(f"  → Gross: ${gross_profit:.2f}, Fee: ${fee:.2f}, Net: ${net_profit:.2f}")
                
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
                
                # TELEGRAM NOTIFICATION
                try:
                    if order['side'] == 'SELL':
                         notifier.send_telegram_message(
                            f"🤖 <b>GRID PROFIT</b>\n"
                            f"Symbol: {self.symbol}\n"
                            f"Price: {order['price']:.2f}\n"
                            f"Profit: ${net_profit:.2f} (Net)"
                         )
                    else:
                         notifier.send_telegram_message(
                            f"🤖 <b>GRID BUY</b>\n"
                            f"Symbol: {self.symbol}\n"
                            f"Price: {order['price']:.2f}\n"
                            f"Qty: {order['qty']}"
                         )
                except Exception as e:
                    self.logger.error(f"Failed to send Telegram alert: {e}")
                
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
    
    def get_status(self):
        """Return current grid status for UI."""
        return {
            'running': self.running,
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
            'current_price': self.get_current_price()
        }
    
    def run(self):
        """Main grid bot loop."""
        self.logger.info(f"Grid Bot started: {self.symbol} ${self.lower_bound}-${self.upper_bound} x{self.grid_count}")
        
        # Place initial orders
        self.place_grid_orders()
        
        while self.running:
            try:
                self.check_order_fills()
                time.sleep(5)  # Check every 5 seconds
            except Exception as e:
                self.logger.error(f"Grid loop error: {e}")
                time.sleep(10)
        
        # Cleanup
        self.cancel_all_orders()
        self.logger.info("Grid Bot stopped.")
    
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

