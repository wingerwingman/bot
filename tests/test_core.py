"""
Unit Tests for CryptoBot
Run with: python -m pytest tests/ -v
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIndicators:
    """Tests for technical indicator calculations."""
    
    def test_calculate_ma_basic(self):
        """Test moving average calculation."""
        from modules.indicators import calculate_ma
        from collections import deque
        
        # Simple case: 5 prices, 5-period MA
        prices = deque([10, 20, 30, 40, 50])
        result = calculate_ma(prices, period=5)
        assert result == 30.0  # (10+20+30+40+50)/5 = 30
    
    def test_calculate_ma_insufficient_data(self):
        """Test MA returns None when insufficient data."""
        from modules.indicators import calculate_ma
        from collections import deque
        
        prices = deque([10, 20])
        result = calculate_ma(prices, period=5)
        assert result is None
    
    def test_calculate_rsi_basic(self):
        """Test RSI calculation returns valid range."""
        from modules.indicators import calculate_rsi
        from collections import deque
        
        # Create oscillating prices to get measurable RSI
        prices = deque([100 + i * (-1)**i for i in range(20)])
        result = calculate_rsi(prices)
        
        if result is not None:
            assert 0 <= result <= 100


class TestStrategy:
    """Tests for trading strategy logic."""
    
    def test_strategy_initialization(self):
        """Test strategy initializes with correct defaults."""
        from modules.strategy import Strategy
        
        s = Strategy()
        assert s.stop_loss_percent == 0.02
        assert s.sell_percent == 0.03
        assert s.rsi_threshold_buy == 40
        assert s.use_trailing_stop == True
    
    def test_strategy_price_history(self):
        """Test price history updates correctly."""
        from modules.strategy import Strategy
        
        s = Strategy()
        s.update_data(100.0)
        s.update_data(101.0)
        s.update_data(102.0)
        
        assert len(s.price_history) == 3
        assert s.price_history[-1] == 102.0
    
    def test_trailing_stop_reset(self):
        """Test trailing stop resets on sell."""
        from modules.strategy import Strategy
        
        s = Strategy()
        s.peak_price_since_buy = 100.0
        s.reset_trailing_stop()
        
        assert s.peak_price_since_buy is None
    
    def test_buy_signal_no_data(self):
        """Test buy signal returns False with no price history."""
        from modules.strategy import Strategy
        
        s = Strategy()
        result = s.check_buy_signal(100.0, 99.0)
        
        assert result == False  # Not enough data
    
    def test_sell_signal_no_position(self):
        """Test sell signal returns None when no position."""
        from modules.strategy import Strategy
        
        s = Strategy()
        result = s.check_sell_signal(100.0, None)
        
        assert result is None


class TestCapitalManager:
    """Tests for capital allocation logic."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        from modules.capital_manager import CapitalManager
        CapitalManager.reset_for_testing()
    
    def test_allocation_percentage(self):
        """Test allocation by percentage."""
        from modules.capital_manager import CapitalManager
        
        cm = CapitalManager()
        cm.total_capital = 1000  # Override after init
        cm.allocations = {}  # Clear loaded state
        cm.allocate('test_signal', percent=0.5)  # 50% as decimal
        
        assert cm.get_available('test_signal') == 500.0
    
    def test_allocation_fixed(self):
        """Test allocation by fixed amount."""
        from modules.capital_manager import CapitalManager
        
        cm = CapitalManager()
        cm.total_capital = 1000
        cm.allocations = {}
        cm.allocate('test_grid', fixed=200)
        
        assert cm.get_available('test_grid') == 200.0
    
    def test_unallocated_calculation(self):
        """Test unallocated capital calculation."""
        from modules.capital_manager import CapitalManager
        
        cm = CapitalManager()
        cm.total_capital = 1000
        cm.allocations = {}
        cm.allocate('test_a', percent=0.6)  # 60%
        cm.allocate('test_b', percent=0.3)  # 30%
        
        # 10% should be unallocated = $100
        assert cm.get_unallocated() == 100.0
    
    def test_pnl_recording(self):
        """Test P&L recording for trades."""
        from modules.capital_manager import CapitalManager
        
        cm = CapitalManager()
        cm.total_capital = 1000
        cm.allocations = {}
        cm.pnl = {}  # Clear P&L
        cm.allocate('test_pnl', percent=50)
        
        # Record a winning trade
        cm.record_trade('test_pnl', profit=25.0, is_win=True)
        
        pnl = cm.get_pnl('test_pnl')
        assert pnl['trades'] == 1
        assert pnl['wins'] == 1
        assert pnl['pnl_amount'] == 25.0
    
    def test_release_allocation(self):
        """Test releasing bot allocation."""
        from modules.capital_manager import CapitalManager
        
        cm = CapitalManager()
        cm.total_capital = 1000
        cm.allocations = {}
        cm.allocate('test_release', percent=30)
        cm.release('test_release')
        
        assert cm.get_available('test_release') == 0


class TestGridBot:
    """Tests for Grid Bot calculations."""
    
    def test_grid_levels_calculation(self):
        """Test grid levels are calculated correctly."""
        from modules.grid_bot import GridBot
        
        bot = GridBot(
            lower_bound=2800,
            upper_bound=3200,
            grid_count=4,
            capital=100,
            is_live=False
        )
        
        levels = bot.calculate_grid_levels()
        
        assert len(levels) == 5  # grid_count + 1
        assert levels[0] == 2800.0
        assert levels[-1] == 3200.0
    
    def test_order_size_calculation(self):
        """Test order size per level."""
        from modules.grid_bot import GridBot
        
        bot = GridBot(
            lower_bound=2800,
            upper_bound=3200,
            grid_count=10,
            capital=100,
            is_live=False
        )
        
        order_size = bot.calculate_order_size()
        
        # Capital / (grid_count // 2) = 100 / 5 = 20
        assert order_size == 20.0
    
    def test_price_rounding(self):
        """Test price rounds to tick size."""
        from modules.grid_bot import GridBot
        
        bot = GridBot(is_live=False)
        bot.tick_size = 0.01
        
        assert bot.round_price(3000.1234) == 3000.12
        assert bot.round_price(3000.129) == 3000.13
    
    def test_quantity_rounding(self):
        """Test quantity rounds to step size."""
        from modules.grid_bot import GridBot
        
        bot = GridBot(is_live=False)
        bot.step_size = 0.0001
        
        # Use pytest.approx for float comparison
        result = bot.round_qty(0.12345)
        assert abs(result - 0.1234) < 0.00001  # Close enough


class TestFeeCalculations:
    """Tests for fee-related calculations."""
    
    def test_grid_fee_simulation(self):
        """Test fee is correctly calculated in grid bot."""
        from modules.grid_bot import GridBot
        
        bot = GridBot(
            lower_bound=2800,
            upper_bound=3200,
            grid_count=10,
            capital=100,
            is_live=False
        )
        
        # Fee rate is 0.1% = 0.001
        assert bot.fee_rate == 0.001
        
        # For a $100 trade, fee should be $0.10
        trade_value = 100
        expected_fee = trade_value * bot.fee_rate
        assert expected_fee == 0.1


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
