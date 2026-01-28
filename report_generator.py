"""
报告生成器模块
"""

import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
from collections import defaultdict

import config
from email_parser import EmailData
from date_utils import DateUtils

logger = logging.getLogger(__name__)


class ReportGenerator:
    """报告生成器类"""
    
    def __init__(self):
        self.date_utils = DateUtils()
    
    def generate_monthly_reports(self, email_data_list: List[EmailData]) -> Dict[str, str]:
        """
        生成月度报告
        
        Args:
            email_data_list: 邮件数据列表
            
        Returns:
            字典，键为文件名，值为报告内容
        """
        try:
            logger.info(f"开始生成月度报告，共 {len(email_data_list)} 封邮件")
            
            # 按月份分组
            monthly_groups = self._group_by_month(email_data_list)
            
            reports = {}
            
            for (year, month), emails in monthly_groups.items():
                logger.info(f"处理 {year}年{month:02d}月 数据，原始邮件数: {len(emails)}")
                
                # 按日期排序
                emails.sort(key=lambda x: x.date)
                
                # 数据去重：同一天保留勤奋时间最长的邮件
                deduplicated_emails = self._deduplicate_emails(emails)
                logger.info(f"去重后 {year}年{month:02d}月 邮件数: {len(deduplicated_emails)}")
                
                # 生成报告内容
                report_content = self._generate_monthly_report_content(year, month, deduplicated_emails)
                
                # 生成文件名
                filename = config.REPORT_FILENAME_FORMAT.format(year=year, month=month)
                
                reports[filename] = report_content
            
            logger.info(f"成功生成 {len(reports)} 个月度报告")
            return reports
            
        except Exception as e:
            logger.error(f"生成月度报告时发生错误: {e}")
            return {}
            
    def _deduplicate_emails(self, emails: List[EmailData]) -> List[EmailData]:
        """
        对邮件列表进行去重，同一天只保留勤奋时间最长的邮件
        
        Args:
            emails: 邮件列表
            
        Returns:
            去重后的邮件列表
        """
        # 按日期分组
        daily_emails = defaultdict(list)
        for email in emails:
            date_str = email.date.strftime('%Y-%m-%d')
            daily_emails[date_str].append(email)
            
        deduplicated = []
        for date_str, day_emails in daily_emails.items():
            if len(day_emails) == 1:
                deduplicated.append(day_emails[0])
            else:
                # 如果同一天有多封邮件，计算每封邮件的勤奋时间
                # 保留时间最长的那个
                logger.info(f"发现 {date_str} 有 {len(day_emails)} 封重复邮件，开始去重处理:")
                for email in day_emails:
                    duration = self._get_email_diligence_duration(email)
                    logger.info(f"  - 文件: {email.filename}, 时长: {duration:.2f}小时")
                
                best_email = max(day_emails, key=lambda e: self._get_email_diligence_duration(e))
                logger.info(f"  > 保留: {best_email.filename}")
                deduplicated.append(best_email)
                
        # 重新按日期排序
        deduplicated.sort(key=lambda x: x.date)
        return deduplicated

    def _get_email_diligence_duration(self, email: EmailData) -> float:
        """
        计算单封邮件中的勤奋时间总时长
        """
        try:
            pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
            matches = re.findall(pattern, email.content)
            
            total_duration = 0.0
            for start_time, end_time in matches:
                total_duration += self._calculate_duration(start_time, end_time)
            
            # 调试日志：如果找到时间，打印一下
            if total_duration > 0:
                pass
                # logger.debug(f"解析到勤奋时间: {email.filename} -> {total_duration}h")
            
            return total_duration
        except Exception:
            return 0.0
    
    def _group_by_month(self, email_data_list: List[EmailData]) -> Dict[Tuple[int, int], List[EmailData]]:
        """
        按月份分组邮件数据
        
        Args:
            email_data_list: 邮件数据列表
            
        Returns:
            按月份分组的字典
        """
        monthly_groups = defaultdict(list)
        
        for email_data in email_data_list:
            if email_data.date:
                month_key = self.date_utils.get_month_year_key(email_data.date)
                monthly_groups[month_key].append(email_data)
        
        return dict(monthly_groups)
    
    def _generate_monthly_report_content(self, year: int, month: int, emails: List[EmailData]) -> str:
        """
        生成单个月份的报告内容
        
        Args:
            year: 年份
            month: 月份
            emails: 该月的邮件列表
            
        Returns:
            Markdown格式的报告内容
        """
        try:
            lines = []
            
            # 标题
            month_title = self.date_utils.format_month_year(year, month)
            lines.append(f"# {month_title}工作总结")
            lines.append("")
            
            # 统计信息
            lines.append("## 📊 统计信息")
            lines.append("")
            lines.append(f"- **总工作日数**: {len(emails)} 天")
            lines.append(f"- **报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            
            # 按日期组织内容
            lines.append("## 📝 工作日志")
            lines.append("")
            
            for email_data in emails:
                lines.extend(self._format_email_entry(email_data))
                lines.append("")
            
            # 月度总结
            lines.append("## 📋 月度总结")
            lines.append("")
            lines.append(f"本月共完成 {len(emails)} 个工作日的日志记录。")
            lines.append("")
            
            # 添加分隔线
            lines.append("---")
            lines.append("")
            lines.append("*此报告由邮件工作总结汇总程序自动生成*")
            
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"生成月度报告内容时发生错误: {e}")
            return f"# 报告生成失败\n\n错误信息: {e}"
    
    def _format_email_entry(self, email_data: EmailData) -> List[str]:
        """
        格式化单个邮件条目
        
        Args:
            email_data: 邮件数据
            
        Returns:
            格式化后的行列表
        """
        lines = []
        
        try:
            # 日期标题
            date_str = email_data.date.strftime("%Y年%m月%d日")
            weekday = self._get_weekday_chinese(email_data.date.weekday())
            lines.append(f"### {date_str} ({weekday})")
            lines.append("")
            
            # 邮件信息
            lines.append(f"**文件名**: `{email_data.filename}`")
            if email_data.subject:
                lines.append(f"**主题**: {email_data.subject}")
            lines.append("")
            
            # 工作内容
            lines.append("**工作内容**:")
            lines.append("")
            
            # 处理邮件内容
            content_lines = email_data.content.split('\n')
            for line in content_lines:
                line = line.strip()
                if line:
                    # 如果是数字开头的行，添加缩进
                    if line[0].isdigit() or line.startswith('•') or line.startswith('-'):
                        lines.append(f"- {line}")
                    else:
                        lines.append(line)
                else:
                    lines.append("")
            
            return lines
            
        except Exception as e:
            logger.error(f"格式化邮件条目时发生错误: {e}")
            return [f"### 格式化失败: {email_data.filename}", "", f"错误: {e}", ""]
    
    def _get_weekday_chinese(self, weekday: int) -> str:
        """
        获取中文星期名称

        Args:
            weekday: 星期数字 (0=Monday, 6=Sunday)

        Returns:
            中文星期名称
        """
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return weekdays[weekday]

    def _parse_time(self, time_str: str) -> int:
        """
        解析时间字符串为分钟数

        Args:
            time_str: 时间字符串，格式如 '17:45'

        Returns:
            从午夜开始的分钟数
        """
        try:
            hours, minutes = map(int, time_str.split(':'))
            return hours * 60 + minutes
        except Exception as e:
            logger.warning(f"解析时间字符串失败: {time_str}, 错误: {e}")
            return 0

    def _calculate_duration(self, start_time: str, end_time: str) -> float:
        """
        计算两个时间之间的时长（小时）

        Args:
            start_time: 开始时间，格式如 '17:45'
            end_time: 结束时间，格式如 '19:45'

        Returns:
            时长（小时）
        """
        start_minutes = self._parse_time(start_time)
        end_minutes = self._parse_time(end_time)

        # 处理跨午夜的情况
        if end_minutes < start_minutes:
            end_minutes += 24 * 60

        duration_minutes = end_minutes - start_minutes
        return duration_minutes / 60.0

    def _calculate_diligence_time_statistics(self) -> Dict[str, any]:
        """
        计算勤奋时间统计

        从已生成的月度报告文件中提取勤奋时间数据并进行统计

        Returns:
            包含月度和年度统计的字典
        """
        try:
            monthly_totals = defaultdict(float)

            # 遍历输出目录中的所有月度报告文件
            for report_file in config.OUTPUT_DIR.glob('*工作总结.md'):
                # 提取年月信息
                match = re.search(r'(\d{4})年(\d{2})月', report_file.name)
                if not match:
                    continue

                year = match.group(1)
                month = match.group(2)
                month_key = f"{year}年{month}月"

                # 读取文件内容
                try:
                    with open(report_file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # 查找所有勤奋时间条目
                    pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
                    matches = re.findall(pattern, content)

                    # 计算该月总时长
                    for start_time, end_time in matches:
                        duration = self._calculate_duration(start_time, end_time)
                        monthly_totals[month_key] += duration

                    logger.debug(f"统计 {month_key} 勤奋时间: {monthly_totals[month_key]:.2f} 小时")

                except Exception as e:
                    logger.warning(f"读取报告文件失败: {report_file}, 错误: {e}")
                    continue

            # 计算年度统计
            yearly_totals = defaultdict(float)
            for month_key, hours in monthly_totals.items():
                year = month_key[:4]
                yearly_totals[f"{year}年"] += hours

            # 计算总计
            total_hours = sum(monthly_totals.values())

            return {
                'monthly': dict(monthly_totals),
                'yearly': dict(yearly_totals),
                'total': total_hours
            }

        except Exception as e:
            logger.error(f"计算勤奋时间统计时发生错误: {e}")
            return {
                'monthly': {},
                'yearly': {},
                'total': 0
            }
    
    def save_reports(self, reports: Dict[str, str]) -> List[Path]:
        """
        保存报告到文件
        
        Args:
            reports: 报告字典，键为文件名，值为内容
            
        Returns:
            保存的文件路径列表
        """
        saved_files = []
        
        try:
            # 确保输出目录存在
            config.OUTPUT_DIR.mkdir(exist_ok=True)
            
            for filename, content in reports.items():
                file_path = config.OUTPUT_DIR / filename
                
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    saved_files.append(file_path)
                    logger.info(f"成功保存报告: {file_path}")
                    
                except Exception as e:
                    logger.error(f"保存报告失败: {file_path}, 错误: {e}")
            
            logger.info(f"共保存 {len(saved_files)} 个报告文件")
            return saved_files
            
        except Exception as e:
            logger.error(f"保存报告时发生错误: {e}")
            return []
    
    def generate_summary_report(self, email_data_list: List[EmailData]) -> str:
        """
        生成总体汇总报告
        
        Args:
            email_data_list: 邮件数据列表
            
        Returns:
            汇总报告内容
        """
        try:
            lines = []
            
            # 标题
            lines.append("# 工作总结汇总报告")
            lines.append("")
            
            # 总体统计
            lines.append("## 📊 总体统计")
            lines.append("")
            lines.append(f"- **总邮件数**: {len(email_data_list)} 封")
            
            # 按月份统计
            monthly_groups = self._group_by_month(email_data_list)
            lines.append(f"- **涵盖月份数**: {len(monthly_groups)} 个月")
            lines.append("")
            
            # 月份详情
            lines.append("## 📅 月份详情")
            lines.append("")
            
            for (year, month), emails in sorted(monthly_groups.items()):
                month_title = self.date_utils.format_month_year(year, month)
                lines.append(f"- **{month_title}**: {len(emails)} 个工作日")
            
            lines.append("")
            
            # 时间范围
            if email_data_list:
                dates = [email.date for email in email_data_list if email.date]
                if dates:
                    min_date = min(dates)
                    max_date = max(dates)
                    lines.append("## 📆 时间范围")
                    lines.append("")
                    lines.append(f"- **开始日期**: {min_date.strftime('%Y年%m月%d日')}")
                    lines.append(f"- **结束日期**: {max_date.strftime('%Y年%m月%d日')}")
                    lines.append("")

            # 勤奋时间统计
            diligence_stats = self._calculate_diligence_time_statistics()
            if diligence_stats['total'] > 0:
                lines.append("## ⏰ 勤奋时间统计")
                lines.append("")

                # 月度勤奋时间
                if diligence_stats['monthly']:
                    lines.append("### 月度勤奋时间")
                    lines.append("")
                    for month_key in sorted(diligence_stats['monthly'].keys()):
                        hours = diligence_stats['monthly'][month_key]
                        lines.append(f"- **{month_key}**: {hours:.2f} 小时")
                    lines.append("")

                # 年度勤奋时间
                if diligence_stats['yearly']:
                    lines.append("### 年度勤奋时间")
                    lines.append("")
                    for year_key in sorted(diligence_stats['yearly'].keys()):
                        hours = diligence_stats['yearly'][year_key]
                        lines.append(f"- **{year_key}总计**: {hours:.2f} 小时")
                    lines.append("")

                # 总计勤奋时间
                lines.append("### 总计勤奋时间")
                lines.append("")
                lines.append(f"- **累计总时长**: {diligence_stats['total']:.2f} 小时")
                lines.append("")

            # 生成信息
            lines.append("## ℹ️ 生成信息")
            lines.append("")
            lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"- **程序版本**: 邮件工作总结汇总程序 v1.0")
            lines.append("")
            
            lines.append("---")
            lines.append("")
            lines.append("*此报告由邮件工作总结汇总程序自动生成*")
            
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"生成汇总报告时发生错误: {e}")
            return f"# 汇总报告生成失败\n\n错误信息: {e}"
