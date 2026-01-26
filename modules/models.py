from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from datetime import datetime
from .database import Base

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    side = Column(String) # BUY / SELL
    price = Column(Float)
    quantity = Column(Float)
    total_value = Column(Float)
    fee = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Extra Context
    reason = Column(String, nullable=True) # Signal, DCA, StopLoss, etc.
    strategy_data = Column(JSON, nullable=True) # RSI, MACD snapshot
    is_paper_trade = Column(Boolean, default=False)
    pnl_amount = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)

class BotState(Base):
    __tablename__ = "bot_states"

    symbol = Column(String, primary_key=True)
    is_active = Column(Boolean, default=False)
    
    # Position Info
    base_balance = Column(Float, default=0.0)
    quote_balance = Column(Float, default=0.0)
    bought_price = Column(Float, nullable=True)
    
    # Strategy State
    dca_count = Column(Integer, default=0)
    peak_price = Column(Float, nullable=True) # For Trailing Stop
    stop_loss_price = Column(Float, nullable=True)
    last_volatility = Column(Float, nullable=True)
    
    # JSON for Strategy Settings & Session Metrics
    configuration = Column(JSON, default=dict) 
    metrics = Column(JSON, default=dict)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class GridState(Base):
    __tablename__ = "grid_states"
    
    symbol = Column(String, primary_key=True)
    is_active = Column(Boolean, default=False)
    
    # Grid Config
    lower_bound = Column(Float)
    upper_bound = Column(Float)
    grid_count = Column(Integer)
    
    # Performance
    total_profit = Column(Float, default=0.0)
    buy_fills = Column(Integer, default=0)
    sell_fills = Column(Integer, default=0)
    
    # JSON blob for list of active/open orders 
    # (Storing complex lists in SQL is cleaner as JSON if not querying deep inside them)
    active_orders = Column(JSON, default=list) 
    
    # Store settings (auto_rebalance, etc) and extra metrics (fees, rebalance_count)
    configuration = Column(JSON, default=dict)
    metrics = Column(JSON, default=dict)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CapitalState(Base):
    __tablename__ = "capital_state"
    
    id = Column(Integer, primary_key=True) # Singleton row usually
    total_capital = Column(Float, default=1000.0)
    
    # Allocations (Percentage 0.0-1.0)
    allocations = Column(JSON, default=dict) # {'live_ETHUSDT': 0.5, 'grid_BTCUSDT': 0.3}
    
    # P&L Tracking
    pnl = Column(JSON, default=dict)
    
    # Real Balances (Synced)
    binance_usdt = Column(Float, default=0.0)
    binance_total_usd = Column(Float, default=0.0)
    
    auto_compound = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
