import re

filepath = r'd:\WorkSpace\Email2Md\output\2025年11月工作总结.md'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Scanning for diligence times:")
total = 0.0
for i, line in enumerate(lines):
    if "勤奋" in line:
        print(f"Line {i+1}: {repr(line.strip())}")
        matches = re.findall(r'\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]', line)
        for start, end in matches:
            h1, m1 = map(int, start.split(':'))
            h2, m2 = map(int, end.split(':'))
            m_start = h1 * 60 + m1
            m_end = h2 * 60 + m2
            if m_end < m_start: m_end += 24*60
            diff = (m_end - m_start) / 60.0
            print(f"  -> Found time: {start} to {end} = {diff} hours")
            total += diff

print(f"Total calculated: {total}")
