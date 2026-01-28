import re

filepath = r'd:\WorkSpace\Email2Md\output\2025年11月工作总结.md'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
for i, line in enumerate(lines):
    if "勤奋" in line:
        print(f"Line {i+1}: {line.strip()}")
