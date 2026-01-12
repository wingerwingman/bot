import logging
import os

# Setup logging manually
logger = logging.getLogger("test_logger")
logger.setLevel(logging.INFO)
fh = logging.FileHandler('trades_us.log')
fh.setFormatter(logging.Formatter('%(asctime)s,%(message)s'))
logger.addHandler(fh)

print("Attempting to write to trades_us.log...")
try:
    logger.info("TEST_ENTRY,1.0,3000.0")
    print("Write executed.")
except Exception as e:
    print(f"Error writing: {e}")

# Check content
if os.path.exists('trades_us.log'):
    with open('trades_us.log', 'r') as f:
        print(f"File content: {f.read()}")
else:
    print("File does not exist!")
