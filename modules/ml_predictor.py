import pandas as pd
import numpy as np
import os
import json
import logging
import time
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# Setup logger
logger = logging.getLogger("ML_Predictor")

class TradePredictor:
    def __init__(self, data_dir='logs'):
        self.data_dir = data_dir
        self.model = None
        self.is_trained = False
        self.min_trades_required = 20  # Need at least 20 trades to start "guessing"
        self.feature_columns = ['rsi', 'volatility', 'volume_ratio', 'fast_ma_slope']
        
    def load_training_data(self):
        """
        Loads trade history from trade_journal.json (or similar).
        Reconstructs features (this is tricky if we didn't save them at trade time).
        For now, we'll assume we start saving 'features' in the trade log, 
        or we'll use a placeholder logic until data accumulates.
        """
        journal_path = os.path.join(self.data_dir, 'trade_journal.json')
        if not os.path.exists(journal_path):
            logger.warning("No trade journal found for ML training.")
            return None
        
        try:
            with open(journal_path, 'r') as f:
                trades = json.load(f)
            
            # Filter for closed trades
            closed_trades = [t for t in trades if t.get('status') == 'closed']
            
            if len(closed_trades) < self.min_trades_required:
                logger.info(f"Not enough trades for ML ({len(closed_trades)}/{self.min_trades_required})")
                return None
                
            # Create DataFrame
            df = pd.DataFrame(closed_trades)
            
            # We need target variable: Did we win?
            # Assuming 'profit_percent' exists
            if 'profit_percent' not in df.columns:
                return None
                
            df['target'] = (df['profit_percent'] > 0).astype(int)
            
            # We need features. If they aren't in the log, we can't really train effectively yet.
            # This implementation assumes future trades will have 'entry_features' dict.
            # For past trades without features, we might have to skip or approximate.
            
            # Extract features from 'indicators' column if it exists
            if 'indicators' in df.columns:
                features_df = pd.json_normalize(df['indicators'])
                data = pd.concat([features_df, df['target']], axis=1)
                
                # Drop rows with NaNs
                data = data.dropna()
                
                return data
            
            return None
            
        except Exception as e:
            logger.error(f"Error loading ML data: {e}")
            return None

    def train(self):
        """Trains the Random Forest model."""
        data = self.load_training_data()
        if data is None or len(data) < self.min_trades_required:
            return False
            
        try:
            X = data[self.feature_columns]
            y = data['target']
            
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            
            self.model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            self.model.fit(X_train, y_train)
            
            # Evaluate
            preds = self.model.predict(X_test)
            acc = accuracy_score(y_test, preds)
            logger.info(f"ML Model Trained. Accuracy: {acc:.2f} on {len(data)} trades")
            
            self.is_trained = True
            return True
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return False

    def predict_quality(self, features):
        """
        Predicts if a trade is likely to be a WIN based on features.
        features: dict e.g. {'rsi': 35, 'volatility': 0.02, ...}
        Returns: probability of win (0.0 to 1.0)
        """
        if not self.is_trained or self.model is None:
            return 0.5  # Neutral / Unknown
        
        try:
            start_time = time.perf_counter()
            
            # Arrange feature vector
            feat_vector = pd.DataFrame([features])[self.feature_columns]
            prob_win = self.model.predict_proba(feat_vector)[0][1] # Probability of class 1 (Win)
            
            elapsed = (time.perf_counter() - start_time) * 1000 # ms
            if elapsed > 50: # Log if slow (>50ms)
                logger.warning(f"⚠️ ML Prediction Slow: {elapsed:.2f}ms")
            
            return prob_win
        except Exception as e:
            logger.error(f"Error predicting: {e}")
            return 0.5
