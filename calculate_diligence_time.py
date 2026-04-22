import re
import os
from datetime import datetime
from collections import defaultdict

from diligence_time import sum_diligence_hours

def extract_year_month(filename):
    """Extract year and month from filename like '2024年07月工作总结.md'"""
    match = re.search(r'(\d{4})年(\d{2})月', filename)
    if match:
        return match.group(1), match.group(2)
    return None, None

# Dictionary to store monthly totals
monthly_totals = defaultdict(float)

# Read all markdown files in the output directory
output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

for filename in os.listdir(output_dir):
    if filename.endswith('工作总结.md') and '年' in filename and '月' in filename:
        year, month = extract_year_month(filename)
        if not year or not month:
            continue

        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all diligence time entries
        month_hours = sum_diligence_hours(content)
        if month_hours <= 0:
            continue

        month_key = f"{year}年{month}月"
        monthly_totals[month_key] += month_hours

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
