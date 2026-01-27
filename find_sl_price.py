
import sys

filename = "modules/trading_bot.py"
print(f"Searching for 'sl_price' in {filename}")

with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f, 1):
        if 'sl_price' in line:
            print(f"{i}: {line.strip()}")
