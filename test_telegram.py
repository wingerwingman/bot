import os
from dotenv import load_dotenv
import requests

load_dotenv()

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

print(f"Testing Telegram...")
print(f"Token: {TOKEN[:5]}..." if TOKEN else "Token: MISSING")
print(f"Chat ID: {CHAT_ID}")

if not TOKEN or not CHAT_ID:
    print("❌ Error: Credentials missing in .env")
    exit()

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "🔔 <b>Beep Boop</b>: This is a test message from your CryptoBot!", "parse_mode": "HTML"}

try:
    res = requests.post(url, json=payload, timeout=10)
    print(f"Status Code: {res.status_code}")
    print(f"Response: {res.text}")
    if res.status_code == 200:
        print("✅ Message Sent! Check your phone.")
    else:
        print("❌ Failed to send.")
except Exception as e:
    print(f"❌ Connection Error: {e}")
