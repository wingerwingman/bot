from modules.database import engine
from sqlalchemy import text

def add_columns():
    with engine.connect() as conn:
        try:
            # SQLite specific ALTER TABLE
            conn.execute(text("ALTER TABLE bot_states ADD COLUMN configuration JSON"))
            print("Added configuration column.")
        except Exception as e:
            print(f"Config column might exist: {e}")
            
        try:
            conn.execute(text("ALTER TABLE bot_states ADD COLUMN metrics JSON"))
            print("Added metrics column to bot_states.")
        except Exception as e:
            print(f"Metrics column might exist in bot_states: {e}")
            
        # Grid States Updates
        try:
            conn.execute(text("ALTER TABLE grid_states ADD COLUMN configuration JSON"))
            print("Added configuration column to grid_states.")
        except Exception as e:
            print(f"Config column might exist in grid_states: {e}")
            
        try:
            conn.execute(text("ALTER TABLE grid_states ADD COLUMN metrics JSON"))
            print("Added metrics column to grid_states.")
        except Exception as e:
            print(f"Metrics column might exist in grid_states: {e}")
            
        # Capital State Updates
        try:
            conn.execute(text("ALTER TABLE capital_state ADD COLUMN pnl JSON"))
            print("Added pnl column to capital_state.")
        except Exception as e:
            print(f"Pnl column might exist in capital_state: {e}")
            
        conn.commit()

if __name__ == "__main__":
    add_columns()
