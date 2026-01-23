"""
Tests for Advanced Strategy Features:
- Multiple Timeframe Analysis (#10)
- Volume Confirmation (#11)
- Cooldown After Stop-Loss (#13)
- Trade Duration Tracking (#4)
- Slippage Tracking (#8)
"""

import pytest
import time
from collections import deque
from unittest.mock import Mock, patch, MagicMock

# Import modules to test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import indicators
from modules.strategy import Strategy


class TestVolumeConfirmation:
    """Tests for Item #11: Volume Confirmation"""
    
    def test_calculate_average_volume(self):
        """Test average volume calculation"""
        volume_series = [100, 150, 200, 120, 180, 160, 140, 130, 170, 150]
        avg = indicators.calculate_average_volume(volume_series, period=5)
        # Last 5 values: 160, 140, 130, 170, 150
        expected = (160 + 140 + 130 + 170 + 150) / 5  # = 150
        assert avg == expected
    
    def test_calculate_average_volume_insufficient_data(self):
        """Test with insufficient data points"""
        volume_series = [100, 150]
        avg = indicators.calculate_average_volume(volume_series, period=5)
        assert avg is None
    
    def test_is_volume_confirmed_above_threshold(self):
        """Test volume confirmation when above multiplier"""
        current_volume = 150
        avg_volume = 100
        multiplier = 1.2
        # 150 >= 100 * 1.2 = 120 -> True
        assert indicators.is_volume_confirmed(current_volume, avg_volume, multiplier) is True
    
    def test_is_volume_confirmed_below_threshold(self):
        """Test volume confirmation when below multiplier"""
        current_volume = 110
        avg_volume = 100
        multiplier = 1.2
        # 110 < 100 * 1.2 = 120 -> False
        assert indicators.is_volume_confirmed(current_volume, avg_volume, multiplier) is False
    
    def test_is_volume_confirmed_no_data(self):
        """Test volume confirmation with no average data"""
        # Should return True (allow trade) when no data
        assert indicators.is_volume_confirmed(100, None, 1.2) is True
        assert indicators.is_volume_confirmed(100, 0, 1.2) is True
    
    def test_strategy_volume_confirmation(self):
        """Test Strategy.check_volume_confirmation method"""
        strategy = Strategy(volume_confirmation_enabled=True, volume_multiplier=1.2)
        
        # Add enough volume history (need 20 for default period)
        for v in [100] * 25:
            strategy.update_volume(v)
        
        # Average is 100, so need 120 for confirmation
        assert strategy.check_volume_confirmation(150) is True
        assert strategy.check_volume_confirmation(110) is False
    
    def test_strategy_volume_confirmation_disabled(self):
        """Test that volume check passes when feature is disabled"""
        strategy = Strategy(volume_confirmation_enabled=False)
        # Should always return True when disabled
        assert strategy.check_volume_confirmation(10) is True


class TestMultiTimeframeAnalysis:
    """Tests for Item #10: Multiple Timeframe Analysis"""
    
    def test_calculate_higher_timeframe_trend_bullish(self):
        """Test bullish trend detection"""
        # Create klines with price above MA50
        klines = [[0, 0, 0, 0, str(100 + i * 0.5)] for i in range(60)]
        # Last price is ~130, MA50 should be lower
        
        result = indicators.calculate_higher_timeframe_trend(klines, ma_period=50)
        
        assert result['trend'] == 'bullish'
        assert result['ma_value'] is not None
        assert result['current_price'] is not None
    
    def test_calculate_higher_timeframe_trend_bearish(self):
        """Test bearish trend detection"""
        # Create klines with price below MA50
        klines = [[0, 0, 0, 0, str(130 - i * 1.0)] for i in range(60)]
        # Last price is ~70, MA50 should be higher
        
        result = indicators.calculate_higher_timeframe_trend(klines, ma_period=50)
        
        assert result['trend'] == 'bearish'
    
    def test_calculate_higher_timeframe_trend_insufficient_data(self):
        """Test with insufficient klines data"""
        klines = [[0, 0, 0, 0, '100'] for _ in range(10)]  # Only 10 candles
        
        result = indicators.calculate_higher_timeframe_trend(klines, ma_period=50)
        
        assert result['trend'] == 'neutral'
    
    def test_strategy_higher_timeframe_check_bullish(self):
        """Test Strategy allows entry in bullish trend"""
        strategy = Strategy(multi_timeframe_enabled=True)
        strategy.set_higher_timeframe_trend({'trend': 'bullish', 'ma_value': 3000, 'current_price': 3100})
        
        assert strategy.check_higher_timeframe_trend() is True
    
    def test_strategy_higher_timeframe_check_bearish(self):
        """Test Strategy blocks entry in bearish trend"""
        strategy = Strategy(multi_timeframe_enabled=True)
        strategy.set_higher_timeframe_trend({'trend': 'bearish', 'ma_value': 3000, 'current_price': 2900})
        
        assert strategy.check_higher_timeframe_trend() is False
    
    def test_strategy_higher_timeframe_disabled(self):
        """Test that HTF check passes when feature is disabled"""
        strategy = Strategy(multi_timeframe_enabled=False)
        strategy.set_higher_timeframe_trend({'trend': 'bearish', 'ma_value': 3000, 'current_price': 2900})
        
        # Should allow entry even with bearish trend when disabled
        assert strategy.check_higher_timeframe_trend() is True


class TestCooldownAfterStopLoss:
    """Tests for Item #13: Cooldown After Stop-Loss"""
    
    def test_cooldown_not_active_initially(self):
        """Test that cooldown is not active before any stop-loss"""
        strategy = Strategy(cooldown_after_stoploss_minutes=30)
        
        assert strategy.is_in_cooldown() is False
        assert strategy.get_cooldown_remaining() == 0
    
    def test_cooldown_activates_after_stoploss(self):
        """Test that cooldown activates after recording stop-loss"""
        strategy = Strategy(cooldown_after_stoploss_minutes=30)
        
        strategy.record_stoploss()
        
        assert strategy.is_in_cooldown() is True
        assert strategy.get_cooldown_remaining() > 29  # Should be close to 30
    
    def test_cooldown_expires(self):
        """Test that cooldown expires after time passes"""
        strategy = Strategy(cooldown_after_stoploss_minutes=0.01)  # 0.6 seconds
        
        strategy.record_stoploss()
        assert strategy.is_in_cooldown() is True
        
        time.sleep(0.7)  # Wait for cooldown to expire
        
        assert strategy.is_in_cooldown() is False
    
    def test_check_buy_signal_blocked_during_cooldown(self):
        """Test that buy signals are blocked during cooldown"""
        strategy = Strategy(cooldown_after_stoploss_minutes=30)
        
        # Setup valid conditions for buy
        for price in [100 - i*0.1 for i in range(300)]:  # Declining for RSI
            strategy.update_data(price)
        
        # Record stop-loss to activate cooldown
        strategy.record_stoploss()
        
        # Buy signal should be blocked
        result = strategy.check_buy_signal(50, 51, current_volume=100)
        assert result is False


class TestTradeDurationTracking:
    """Tests for Item #4: Trade Duration Tracking"""
    
    def test_trade_duration_initial_state(self):
        """Test initial state of duration tracking"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.entry_time = None
            bot.total_hold_time_minutes = 0
            bot.trade_durations = []
            
            duration = bot.record_trade_duration()
            assert duration == 0
            assert bot.get_average_trade_duration() == 0
    
    def test_trade_duration_calculation(self):
        """Test duration calculation after trade"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.entry_time = time.time() - 120  # 2 minutes ago
            bot.total_hold_time_minutes = 0
            bot.trade_durations = []
            
            duration = bot.record_trade_duration()
            
            assert 1.9 < duration < 2.1  # ~2 minutes
            assert len(bot.trade_durations) == 1
            assert bot.entry_time is None  # Reset after recording
    
    def test_average_trade_duration(self):
        """Test average duration calculation"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.trade_durations = [10, 20, 30]  # 10, 20, 30 minutes
            
            avg = bot.get_average_trade_duration()
            assert avg == 20  # (10 + 20 + 30) / 3


class TestSlippageTracking:
    """Tests for Item #8: Slippage Tracking"""
    
    def test_slippage_calculation_buy(self):
        """Test slippage calculation on buy order"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.total_slippage = 0
            bot.slippage_events = []
            bot.logger = Mock()
            
            # Expected $100, got $100.50 (0.5% slippage)
            slippage = bot.calculate_slippage(100.00, 100.50, 1.0)
            
            assert slippage == 0.50
            assert bot.total_slippage == 0.50
            assert len(bot.slippage_events) == 1
            assert bot.slippage_events[0]['slippage_percent'] == 0.5
    
    def test_slippage_accumulation(self):
        """Test slippage accumulates across trades"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.total_slippage = 0
            bot.slippage_events = []
            bot.logger = Mock()
            
            bot.calculate_slippage(100.00, 100.10, 1.0)  # $0.10 slippage
            bot.calculate_slippage(200.00, 200.50, 1.0)  # $0.50 slippage
            
            assert bot.total_slippage == pytest.approx(0.60, abs=0.01)
            assert len(bot.slippage_events) == 2
    
    def test_slippage_logging_threshold(self):
        """Test that significant slippage is logged"""
        from modules.trading_bot import BinanceTradingBot
        
        with patch.object(BinanceTradingBot, '__init__', lambda x: None):
            bot = BinanceTradingBot()
            bot.total_slippage = 0
            bot.slippage_events = []
            bot.logger = Mock()
            
            # Slippage > 0.1% should log
            bot.calculate_slippage(100.00, 100.20, 1.0)  # 0.2%
            
            bot.logger.info.assert_called_once()


class TestIntegration:
    """Integration tests for combined features"""
    
    def test_buy_signal_with_all_filters(self):
        """Test that all new filters work together in check_buy_signal"""
        strategy = Strategy(
            volume_confirmation_enabled=True,
            volume_multiplier=1.2,
            multi_timeframe_enabled=True,
            cooldown_after_stoploss_minutes=30
        )
        
        # Setup price history for valid buy signal
        for price in [100 - i*0.1 for i in range(250)]:
            strategy.update_data(price, volume=100)
        
        # Set bullish higher timeframe
        strategy.set_higher_timeframe_trend({'trend': 'bullish', 'ma_value': 50, 'current_price': 55})
        
        # Test with sufficient volume (should check RSI/MACD conditions)
        # Note: This may still return False due to RSI/MACD but won't be blocked by new filters
        current_price = 20
        current_volume = 150  # Above 100 * 1.2 = 120
        
        # The function should at least pass the new filter checks
        # (may fail on RSI/MACD but that's expected)
        result = strategy.check_buy_signal(current_price, 21, current_volume)
        
        # We can't guarantee True, but we can verify filters aren't blocking
        assert strategy.is_in_cooldown() is False
        assert strategy.check_higher_timeframe_trend() is True
        assert strategy.check_volume_confirmation(current_volume) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
