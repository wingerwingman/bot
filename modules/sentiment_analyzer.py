import requests
import time
import logging
from . import config

# Try to import TextBlob for sentiment, fallback to simple keyword match
try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False

class SentimentAnalyzer:
    """
    Fetches crypto news/social sentiment and scores it.
    Score Range: -1.0 (Extremely Bearish) to +1.0 (Extremely Bullish)
    """
    
    def __init__(self, api_key=None, symbol="ETH"):
        self.logger = logging.getLogger("SentimentAnalyzer")
        self.api_key = api_key or config.CRYPTOPANIC_API_KEY
        self.symbol = symbol.replace('USDT', '') # ETHUSDT -> ETH
        self.last_score = 0.0
        self.last_update = 0
        self.cache_duration = 900 # 15 Minutes
        
    def get_sentiment_score(self):
        """
        Returns the current sentiment score (-1 to 1).
        Cached for 15 minutes to avoid API limits.
        """
        if time.time() - self.last_update < self.cache_duration:
            return self.last_score
            
        score = self.fetch_fresh_sentiment()
        self.last_score = score
        self.last_update = time.time()
        return score

    def fetch_fresh_sentiment(self):
        """
        Fetches news from CryptoPanic and analyzes it.
        """
        if not self.api_key:
            self.logger.warning("No CryptoPanic API Key provided. Sentiment defaults to NEUTRAL (0.0).")
            return 0.0
            
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={self.api_key}&currencies={self.symbol}&kind=news&filter=hot"
        
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if 'results' not in data:
                return 0.0
                
            posts = data['results']
            total_score = 0
            count = 0
            
            for post in posts[:15]: # Analyze top 15 hot posts
                title = post.get('title', '')
                
                # 1. API's own 'panic'/'bullish' votes if available (Pro feature usually, but some basic info might exist)
                # votes = post.get('votes', {})
                # ... process votes ...
                
                # 2. Text Analysis
                score = self.analyze_text(title)
                total_score += score
                count += 1
                
            if count == 0:
                return 0.0
                
            avg_score = total_score / count
            self.logger.info(f"Updated Sentiment for {self.symbol}: {avg_score:.2f} (based on {count} news items)")
            return avg_score

        except Exception as e:
            self.logger.error(f"Error fetching sentiment: {e}")
            return 0.0
            
    def analyze_text(self, text):
        """
        Analyzes text and returns polarity (-1 to 1).
        """
        if TEXTBLOB_AVAILABLE:
            blob = TextBlob(text)
            return blob.sentiment.polarity
        else:
            # Fallback: Simple Keyword Matching
            text = text.lower()
            if any(w in text for w in ['bull', 'surge', 'soar', 'high', 'breakout', 'gain']):
                return 0.5
            if any(w in text for w in ['bear', 'crash', 'drop', 'low', 'dump', 'loss', 'ban']):
                return -0.5
            return 0.0

# Singleton or Factory if needed, but Strategy will instantiate it.
