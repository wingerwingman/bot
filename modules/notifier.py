import requests
import logging
from . import config

logger = logging.getLogger("BinanceTradingBot")

def send_telegram_message(message):
    """
    Sends a message to the configured Telegram chat.
    """
    token = config.TELEGRAM_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    
    if not token or not chat_id:
        logger.debug("Telegram notification skipped: Credentials not set.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            logger.error(f"Failed to send Telegram message: {response.text}")
        else:
            logger.debug("Telegram message sent successfully.")
    except Exception as e:
        logger.error(f"Telegram connection error: {e}")
