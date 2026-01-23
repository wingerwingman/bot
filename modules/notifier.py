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

def send_daily_summary(stats):
    """
    Sends a daily summary report via Telegram.
    
    Args:
        stats: Dictionary containing performance metrics
            - total_trades
            - win_rate
            - net_pnl
            - top_winner
            - total_fees
    """
    if not config.TELEGRAM_TOKEN:
        return

    emoji = "🚀" if stats.get('net_pnl', 0) >= 0 else "📉"
    
    msg = (
        f"📅 <b>DAILY TRADING SUMMARY</b> {emoji}\n\n"
        f"<b>Performance:</b>\n"
        f"• Trades: {stats.get('total_trades', 0)}\n"
        f"• Win Rate: {stats.get('win_rate', 0)}%\n"
        f"• Net P&L: <b>${stats.get('net_pnl', 0.0):.2f}</b>\n"
        f"• Fees Paid: ${stats.get('total_fees', 0.0):.2f}\n\n"
        f"<b>Highlights:</b>\n"
        f"• Best Win: ${stats.get('top_winner', 0.0):.2f}\n"
        f"• Max Drawdown: {stats.get('max_drawdown', 0.0)}%\n"
    )
    
    send_telegram_message(msg)
