#!/usr/bin/env python3
import re

# Read the file
with open('readme', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Process each line: remove trailing spaces
lines = [line.rstrip() + '\n' if line.rstrip() else '\n' for line in lines]

# Join back to string for regex processing
content = ''.join(lines)

# Fix multiple consecutive blank lines
content = re.sub(r'\n\n\n+', '\n\n', content)

# Write back
with open('readme', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Removed trailing spaces (MD009)")
print("✓ Collapsed multiple blank lines (MD012)")
