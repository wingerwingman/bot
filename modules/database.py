import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

# Database File Path
DB_FOLDER = "data"
DB_FILE = "bot_data.db"
DB_PATH = os.path.join(DB_FOLDER, DB_FILE)

# Ensure data directory exists
if not os.path.exists(DB_FOLDER):
    os.makedirs(DB_FOLDER)

# SQLite Connection String
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Create Engine
# check_same_thread=False is required for SQLite with Flask/Threading
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Create Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Scoped Session for Thread Safety (Important for Flask + Background Threads)
db_session = scoped_session(SessionLocal)

# Base class for models
Base = declarative_base()
Base.query = db_session.query_property()

def init_db():
    """Creates tables if they don't exist and performs auto-migration for missing columns."""
    import modules.models  # Import models to register them
    Base.metadata.create_all(bind=engine)
    
    # Auto-Migration: Check for new columns and add them if missing
    # This prevents 'no such column' errors for users updating from older versions
    from sqlalchemy import text
    
    with engine.connect() as conn:
        try:
             # Check BotState columns
             conn.execute(text("ALTER TABLE bot_states ADD COLUMN configuration JSON"))
             print("✅ Auto-Migration: Added 'configuration' to bot_states")
        except: pass
        
        try:
             conn.execute(text("ALTER TABLE bot_states ADD COLUMN metrics JSON"))
             print("✅ Auto-Migration: Added 'metrics' to bot_states")
        except: pass

        try:
             # Check GridState columns
             conn.execute(text("ALTER TABLE grid_states ADD COLUMN configuration JSON"))
             print("✅ Auto-Migration: Added 'configuration' to grid_states")
        except: pass
        
        try:
             conn.execute(text("ALTER TABLE grid_states ADD COLUMN metrics JSON"))
             print("✅ Auto-Migration: Added 'metrics' to grid_states")
        except: pass
        
        try:
             # Check CapitalState columns
             conn.execute(text("ALTER TABLE capital_state ADD COLUMN pnl JSON"))
             print("✅ Auto-Migration: Added 'pnl' to capital_state")
        except: pass

        # Force commit for SQLite (critical!)
        conn.commit()
    
    # Check if we need to migrate metrics (If Capital is 0, we can assume it's fresh DB)
    try:
        from .models import CapitalState
        # Don't use a scoped session here to avoid binding issues during init
        # Just use raw connection or a temp session
        temp_session = SessionLocal()
        cap = temp_session.query(CapitalState).filter_by(id=1).first()
        
        # Smart Migration Trigger:
        # Run if:
        # 1. No Capital State exists (New DB)
        # 2. OR Total Capital is 0 (Fresh DB)
        # 3. OR PnL is empty (Balance synced but history missing - USER CASE)
        should_migrate = False
        if not cap:
            should_migrate = True
        elif cap.total_capital == 0:
            should_migrate = True
        elif not cap.pnl: # Checks for empty dict {} or None
            should_migrate = True
            
        if should_migrate:
            import os
            # Check if source files exist before trying
            if os.path.exists('data/capital_state.json') or os.path.exists('data/state_live_ETHUSDT.json'):
                print("⚠️  Missing History Detected. Attempting to migrate legacy JSON data...")
                try:
                    import subprocess
                    # Use sys.executable to ensure we use the same python interpreter
                    import sys
                    subprocess.run([sys.executable, "scripts/migrate_json_to_db.py"], check=True)
                    print("✅ Data Migration Script executed successfully.")
                except Exception as ex:
                    print(f"Migration warning: {ex}")
        else:
            # print("DB already populated. Skipping migration.")
            pass
    except Exception as e:
        print(f"Skipping migration check: {e}")

def get_db():
    """Dependency for getting DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
