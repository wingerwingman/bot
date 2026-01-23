import os

file_path = 'IMPROVEMENTS.md'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
skipped_sections = [
    '### 1. Trade Journal',
    '### 3. Sharpe Ratio',
    '### 6. Indicator Snapshots',
    '### 15. Equity Curve',
    '### 16. Trade History',
    '### 25. Warning Alerts'
]

# Items to remove from Priority List
priority_removals = [
    'Trade journal with context',
    'Equity curve storage',
    'Trade history table UI',
    'indicator snapshots',
    'warning alerts'
]

for line in lines:
    # Check if this line starts a section we want to remove
    is_target_header = False
    for s in skipped_sections:
        if line.strip().startswith(s):
            is_target_header = True
            break
    
    if is_target_header:
        skip = True
    elif skip and (line.strip().startswith('### ') or line.strip().startswith('## ')):
        skip = False
    
    # Filter Priority List items
    remove_priority_line = False
    for p in priority_removals:
        if p.lower() in line.lower() and ('Priority' not in line): # Logic check
            if line.strip()[0].isdigit(): # Only remove numbered list items
                remove_priority_line = True
    
    if not skip and not remove_priority_line:
        new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
    
print("Cleaned up IMPROVEMENTS.md")
