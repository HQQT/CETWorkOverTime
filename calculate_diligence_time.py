import re
import os
from datetime import datetime
from collections import defaultdict

def parse_time(time_str):
    """Parse time string like '17:45' to minutes since midnight"""
    hours, minutes = map(int, time_str.split(':'))
    return hours * 60 + minutes

def calculate_duration(start_time, end_time):
    """Calculate duration in hours between two time strings"""
    start_minutes = parse_time(start_time)
    end_minutes = parse_time(end_time)

    # Handle cases where end time is past midnight
    if end_minutes < start_minutes:
        end_minutes += 24 * 60

    duration_minutes = end_minutes - start_minutes
    return duration_minutes / 60.0

def extract_year_month(filename):
    """Extract year and month from filename like '2024年07月工作总结.md'"""
    match = re.search(r'(\d{4})年(\d{2})月', filename)
    if match:
        return match.group(1), match.group(2)
    return None, None

# Dictionary to store monthly totals
monthly_totals = defaultdict(float)

# Read all markdown files in the output directory
output_dir = r'D:\WorkSpace\Email2Md\output'

for filename in os.listdir(output_dir):
    if filename.endswith('工作总结.md') and '年' in filename and '月' in filename:
        year, month = extract_year_month(filename)
        if not year or not month:
            continue

        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all diligence time entries
        pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
        matches = re.findall(pattern, content)

        month_key = f"{year}年{month}月"
        for start_time, end_time in matches:
            duration = calculate_duration(start_time, end_time)
            monthly_totals[month_key] += duration

# Sort by year and month
sorted_months = sorted(monthly_totals.keys(), key=lambda x: (x[:4], x[5:7]))

# Calculate yearly totals
yearly_totals = defaultdict(float)
for month_key, hours in monthly_totals.items():
    year = month_key[:4]
    yearly_totals[year] += hours

# Print results
print("=" * 60)
print("月度勤奋时间统计")
print("=" * 60)
for month_key in sorted_months:
    hours = monthly_totals[month_key]
    print(f"{month_key}: {hours:.2f} 小时")

print("\n" + "=" * 60)
print("年度勤奋时间统计")
print("=" * 60)
for year in sorted(yearly_totals.keys()):
    hours = yearly_totals[year]
    print(f"{year}年: {hours:.2f} 小时")

print("\n" + "=" * 60)
print("总计勤奋时间")
print("=" * 60)
total_hours = sum(monthly_totals.values())
print(f"总计: {total_hours:.2f} 小时")
