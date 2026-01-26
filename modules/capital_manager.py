"""
Capital Manager Module
Manages capital allocation and P&L tracking across multiple bots.
Ensures bots don't compete for the same funds.
"""

import threading
import json
import os
import logging
from datetime import datetime
from binance import Client
from . import config
from . import logger_setup

# Get logger instance
logger = logging.getLogger("CapitalManager")


class CapitalManager:
    """
    Singleton class to manage capital allocation across bots.
    
    Features:
    - Set total available capital
    - Reserve capital per bot (by percentage or fixed amount)
    - Track P&L per bot
    - Prevent over-allocation
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.total_capital = 0.0
        
        # Allocations: {bot_id: {"percent": 0.5, "fixed": None, "reserved": 500.0}}
        self.allocations = {}
        
        # P&L Tracking: {bot_id: {"starting": 500, "current": 545, "trades": 10, "wins": 6}}
        self.pnl = {}
        
        # Auto-compound toggle
        self.auto_compound = False
        
        # Binance balance cache
        self.binance_balance = {'usdt': 0.0, 'eth': 0.0, 'total_usd': 0.0}
        
        # State file for persistence
        self.state_file = "data/capital_state.json"
        
        # Load saved state
        self._load_state()
    
    @classmethod
    def reset_for_testing(cls):
        """Reset singleton instance for unit testing."""
        with cls._lock:
            cls._instance = None
    
    def _save_state(self):
        """Persist state to Database (SQLAlchemy)."""
        try:
            from .database import db_session
            from .models import CapitalState
            
            session = db_session()
            
            # Singleton ID = 1
            state = session.query(CapitalState).filter_by(id=1).first()
            if not state:
                state = CapitalState(id=1)
                session.add(state)
            
            state.total_capital = self.total_capital
            state.allocations = self.allocations
            state.pnl = self.pnl
            state.auto_compound = self.auto_compound
            
            if self.binance_balance:
                state.binance_usdt = self.binance_balance.get('usdt', 0.0)
                state.binance_total_usd = self.binance_balance.get('total_usd', 0.0)
                
            session.commit()
            session.close()

        except Exception as e:
            logger.error(f"Error saving capital state to DB: {e}")
    
    def _load_state(self):
        """Load state from Database (SQLAlchemy)."""
        try:
            from .database import db_session
            from .models import CapitalState
            
            session = db_session()
            state = session.query(CapitalState).filter_by(id=1).first()
            
            if state:
                self.total_capital = state.total_capital or 0.0
                self.allocations = state.allocations or {}
                self.pnl = state.pnl or {}
                self.auto_compound = state.auto_compound or False
                
            session.close()
                
        except Exception as e:
            logger.error(f"Error loading capital state from DB: {e}")
    
    def set_total_capital(self, amount):
        """Set the total capital pool."""
        self.total_capital = float(amount)
        self._recalculate_reservations()
        self._save_state()
    
    def _recalculate_reservations(self):
        """Recalculate reserved amounts based on percentages."""
        for bot_id, alloc in self.allocations.items():
            if alloc.get('percent') is not None:
                alloc['reserved'] = self.total_capital * alloc['percent']
    
    def allocate(self, bot_id, percent=None, fixed=None):
        """
        Allocate capital to a bot.
        
        Args:
            bot_id: Unique identifier for the bot (e.g., 'signal', 'grid')
            percent: Percentage of total capital (0.0-1.0)
            fixed: Fixed dollar amount
        """
        if percent is not None:
            reserved = self.total_capital * percent
            self.allocations[bot_id] = {
                'percent': percent,
                'fixed': None,
                'reserved': reserved
            }
        elif fixed is not None:
            self.allocations[bot_id] = {
                'percent': None,
                'fixed': fixed,
                'reserved': min(fixed, self.total_capital)
            }
        
        # Initialize P&L tracking
        if bot_id not in self.pnl:
            self.pnl[bot_id] = {
                'starting': self.allocations[bot_id]['reserved'],
                'current': self.allocations[bot_id]['reserved'],
                'realized_pnl': 0.0,
                'trades': 0,
                'wins': 0
            }
        
        self._save_state()
    
    def release(self, bot_id):
        """Release allocation when bot stops."""
        if bot_id in self.allocations:
            del self.allocations[bot_id]
            self._save_state()
    
    def get_available(self, bot_id):
        """Get the reserved capital for a specific bot."""
        if bot_id in self.allocations:
            return self.allocations[bot_id].get('reserved', 0.0)
        return 0.0
    
    def get_unallocated(self):
        """Get the amount of capital not allocated to any bot."""
        total_reserved = sum(a.get('reserved', 0) for a in self.allocations.values())
        return max(0, self.total_capital - total_reserved)
    
    def record_trade(self, bot_id, profit, is_win):
        """
        Record a trade result for P&L tracking.
        
        Args:
            bot_id: Which bot made the trade
            profit: Profit/loss amount (can be negative)
            is_win: Whether the trade was profitable
        """
        if bot_id not in self.pnl:
            self.pnl[bot_id] = {
                'starting': 0,
                'current': 0,
                'realized_pnl': 0.0,
                'trades': 0,
                'wins': 0
            }
        
        self.pnl[bot_id]['realized_pnl'] += profit
        self.pnl[bot_id]['current'] += profit
        self.pnl[bot_id]['trades'] += 1
        if is_win:
            self.pnl[bot_id]['wins'] += 1
        
        # Auto-compound: add profit to allocation
        if self.auto_compound and profit > 0 and bot_id in self.allocations:
            self.allocations[bot_id]['reserved'] += profit
            # Also increase total capital
            self.total_capital += profit
        
        self._save_state()
    
    def get_pnl(self, bot_id):
        """Get P&L stats for a specific bot."""
        if bot_id in self.pnl:
            stats = self.pnl[bot_id]
            starting = stats.get('starting', 0)
            current = stats.get('current', starting)
            pnl_amount = stats.get('realized_pnl', 0)
            pnl_percent = (pnl_amount / starting * 100) if starting > 0 else 0
            win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
            
            return {
                'starting': starting,
                'current': current,
                'pnl_amount': pnl_amount,
                'pnl_percent': pnl_percent,
                'trades': stats['trades'],
                'wins': stats['wins'],
                'win_rate': win_rate
            }
        return None
    
    def get_status(self):
        """Get full status for UI display."""
        bots_status = {}
        for bot_id in set(list(self.allocations.keys()) + list(self.pnl.keys())):
            bots_status[bot_id] = {
                'allocated': self.get_available(bot_id),
                'percent': self.allocations.get(bot_id, {}).get('percent', 0) * 100 if self.allocations.get(bot_id, {}).get('percent') else None,
                'pnl': self.get_pnl(bot_id)
            }
        
        total_pnl = sum(
            self.pnl.get(b, {}).get('realized_pnl', 0) 
            for b in self.pnl
        )
        
        return {
            'total_capital': self.total_capital,
            'unallocated': self.get_unallocated(),
            'bots': bots_status,
            'combined_pnl': total_pnl,
            'combined_pnl_percent': (total_pnl / self.total_capital * 100) if self.total_capital > 0 else 0,
            'auto_compound': self.auto_compound,
            'binance_balance': self.binance_balance
        }
    
    def reset_pnl(self, bot_id=None):
        """Reset P&L tracking for a bot or all bots."""
        if bot_id:
            if bot_id in self.pnl:
                starting = self.get_available(bot_id)
                self.pnl[bot_id] = {
                    'starting': starting,
                    'current': starting,
                    'realized_pnl': 0.0,
                    'trades': 0,
                    'wins': 0
                }
        else:
            for b_id in self.pnl:
                starting = self.get_available(b_id)
                self.pnl[b_id] = {
                    'starting': starting,
                    'current': starting,
                    'realized_pnl': 0.0,
                    'trades': 0,
                    'wins': 0
                }
        self._save_state()
    
    def set_auto_compound(self, enabled):
        """Enable or disable auto-compounding."""
        self.auto_compound = bool(enabled)
        self._save_state()
    
    def sync_from_binance(self):
        """
        Fetch current balances from Binance and update total capital.
        Returns the fetched balances.
        """
        try:
            client = Client(config.API_KEY, config.API_SECRET, tld='us')
            
            # Get USDT balance
            usdt_balance = 0.0
            eth_balance = 0.0
            eth_price = 0.0
            
            account = client.get_account()
            for asset in account['balances']:
                if asset['asset'] == 'USDT':
                    usdt_balance = float(asset['free']) + float(asset['locked'])
                elif asset['asset'] == 'ETH':
                    eth_balance = float(asset['free']) + float(asset['locked'])
            
            # Get ETH price for USD conversion
            try:
                ticker = client.get_symbol_ticker(symbol='ETHUSDT')
                eth_price = float(ticker['price'])
            except Exception as e:
                logger.error(f"Failed to get ETH price: {e}")
                eth_price = 0.0
            
            eth_value_usd = eth_balance * eth_price
            
            # USDT is the tradable capital - ETH is considered "in positions"
            # Only sync USDT as available capital for new trades
            available_capital = usdt_balance
            
            self.binance_balance = {
                'usdt': usdt_balance,
                'eth': eth_balance,
                'eth_price': eth_price,
                'eth_value_usd': eth_value_usd,
                'total_usd': usdt_balance + eth_value_usd,  # For reference only
                'available_capital': available_capital  # USDT only - what's actually usable
            }
            
            # Update total capital to only usable USDT
            self.total_capital = available_capital
            
            self._save_state()
            return self.binance_balance
            
        except Exception as e:
            logger.error(f"Error syncing from Binance: {e}")
            return None
    
    def validate_allocation(self):
        """
        Check if allocations exceed actual Binance balance.
        Returns (is_valid, message).
        """
        if self.binance_balance.get('total_usd', 0) == 0:
            return True, "No Binance balance synced yet"
        
        total_allocated = sum(a.get('reserved', 0) for a in self.allocations.values())
        actual_balance = self.binance_balance.get('total_usd', 0)
        
        if total_allocated > actual_balance:
            return False, f"Over-allocated! Allocated ${total_allocated:.2f} but only ${actual_balance:.2f} available"
        
        return True, f"OK: ${total_allocated:.2f} allocated of ${actual_balance:.2f} available"


# Global instance
capital_manager = CapitalManager()
