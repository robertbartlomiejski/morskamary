import re

# Read the file
with open('readme', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add top-level heading at the beginning (MD041)
if not content.startswith('# '):
    content = '# MORSKAMARY: Blue Sociology Research Repository\n\n' + content

# 2. Remove trailing spaces (MD009)
lines = content.split('\n')
lines = [line.rstrip() for line in lines]
content = '\n'.join(lines)

# 3. Collapse multiple blank lines to single blank line (MD012)
content = re.sub(r'\n\n\n+', '\n\n', content)

# Write back
with open('readme', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Fixed MD041 (top-level heading)")
print("✓ Fixed MD009 (trailing spaces)")
print("✓ Fixed MD012 (multiple blank lines)")
