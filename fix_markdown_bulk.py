#!/usr/bin/env python3
"""Bulk fix markdown files in data/derived folder"""
import os
import re
from pathlib import Path

def fix_markdown_file(filepath):
    """Fix common markdown linting issues"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove trailing spaces from each line
    lines = content.split('\n')
    lines = [line.rstrip() for line in lines]
    content = '\n'.join(lines)
    
    # Collapse multiple consecutive blank lines to single blank
    content = re.sub(r'\n\n\n+', '\n\n', content)
    
    # Ensure file ends with single newline
    content = content.rstrip() + '\n'
    
    # Add H1 heading if missing (MD041)
    if not content.startswith('# '):
        title = Path(filepath).stem.replace(' — kopia', '')
        content = f'# {title}\n\n' + content
    
    # Fix bare URLs by wrapping in angle brackets (MD034)
    # Match URLs not already in brackets
    content = re.sub(r'(?<![(\[])(https?://[^\s\n)]+)(?![)\]])', r'<\1>', content)
    
    # Add blank line after headings if missing (MD022)
    # If heading is not followed by blank line (unless it's end of file)
    content = re.sub(r'^(#{1,6} .+)$\n(?![\n])', r'\1\n\n', content, flags=re.MULTILINE)
    
    # Add blank line before lists (MD032)
    content = re.sub(r'([^\n])\n([-*+] )', r'\1\n\n\2', content)
    
    # Add blank line after lists (MD032)
    content = re.sub(r'([-*+] .+)\n(?![^\n]*[-*+] )', r'\1\n', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return True

# Change to data/derived folder
os.chdir('data/derived')

# Fix all markdown files
md_files = sorted([f for f in os.listdir('.') if f.endswith('.md')])
fixed_count = 0
for md_file in md_files:
    try:
        if fix_markdown_file(md_file):
            fixed_count += 1
            print(f"✓ {md_file}")
    except Exception as e:
        print(f"✗ {md_file}: {e}")

print(f"\n✓ Fixed {fixed_count} markdown files")
