"""
邮件处理器模块
"""

import logging
from pathlib import Path
from typing import List, Optional
import sys

import config
from email_parser import EmailParser, EmailData
from report_generator import ReportGenerator
from date_utils import DateUtils

logger = logging.getLogger(__name__)


class EmailProcessor:
    """邮件处理器主类"""
    
    def __init__(self, work_dir: Optional[Path] = None):
        """
        初始化邮件处理器
        
        Args:
            work_dir: 工作目录路径，默认使用配置中的目录
        """
        self.work_dir = work_dir or config.WORK_SUMMARY_DIR
        self.email_parser = EmailParser()
        self.report_generator = ReportGenerator()
        self.date_utils = DateUtils()
        
        # 验证工作目录
        if not self.work_dir.exists():
            raise FileNotFoundError(f"工作目录不存在: {self.work_dir}")
        
        logger.info(f"邮件处理器初始化完成，工作目录: {self.work_dir}")
    
    def process_all_emails(self) -> bool:
        """
        处理所有邮件文件
        
        Returns:
            处理是否成功
        """
        try:
            logger.info("开始处理所有邮件文件")
            
            # 扫描邮件文件
            email_files = self._scan_email_files()
            if not email_files:
                logger.warning("未找到任何邮件文件")
                return False
            
            logger.info(f"找到 {len(email_files)} 个邮件文件")
            
            # 解析邮件文件
            email_data_list = self._parse_email_files(email_files)
            if not email_data_list:
                logger.error("没有成功解析任何邮件文件")
                return False
            
            logger.info(f"成功解析 {len(email_data_list)} 个邮件文件")
            
            # 生成报告
            success = self._generate_and_save_reports(email_data_list)
            
            if success:
                logger.info("邮件处理完成")
                return True
            else:
                logger.error("报告生成失败")
                return False
                
        except Exception as e:
            logger.error(f"处理邮件时发生错误: {e}")
            return False
    
    def _scan_email_files(self) -> List[Path]:
        """
        扫描工作目录中的邮件文件
        
        Returns:
            邮件文件路径列表
        """
        try:
            email_files = []
            
            # 扫描所有.eml文件
            for file_path in self.work_dir.glob(f"*{config.EMAIL_FILE_EXTENSION}"):
                if file_path.is_file():
                    # 检查是否应该排除
                    if not self.date_utils.should_exclude_file(file_path.name):
                        email_files.append(file_path)
                    else:
                        logger.debug(f"排除文件: {file_path.name}")
            
            # 按文件名排序
            email_files.sort(key=lambda x: x.name)
            
            logger.info(f"扫描完成，找到 {len(email_files)} 个有效邮件文件")
            return email_files
            
        except Exception as e:
            logger.error(f"扫描邮件文件时发生错误: {e}")
            return []
    
    def _parse_email_files(self, email_files: List[Path]) -> List[EmailData]:
        """
        解析邮件文件列表

        Args:
            email_files: 邮件文件路径列表

        Returns:
            成功解析的邮件数据列表
        """
        email_data_list = []
        failed_count = 0

        for i, file_path in enumerate(email_files, 1):
            try:
                logger.info(f"解析进度: {i}/{len(email_files)} - {file_path.name}")

                email_data = self.email_parser.parse_email_file(file_path)
                if email_data:
                    email_data_list.append(email_data)
                    logger.debug(f"成功解析: {file_path.name}")
                else:
                    failed_count += 1
                    logger.warning(f"解析失败: {file_path.name}")

            except Exception as e:
                failed_count += 1
                logger.error(f"解析文件时发生异常: {file_path.name}, 错误: {e}")

        # 处理重复文件
        email_data_list = self._handle_duplicate_emails(email_data_list)

        logger.info(f"解析完成: 成功 {len(email_data_list)} 个，失败 {failed_count} 个")
        return email_data_list

    def _handle_duplicate_emails(self, email_data_list: List[EmailData]) -> List[EmailData]:
        """
        处理重复邮件，智能合并同一日期的多个邮件
        规则：保留勤奋时间最长的那封邮件

        Args:
            email_data_list: 原始邮件数据列表

        Returns:
            处理后的邮件数据列表
        """
        from collections import defaultdict
        import re

        # 按日期分组
        date_groups = defaultdict(list)
        for email_data in email_data_list:
            if email_data.date:
                date_key = email_data.date.strftime('%Y-%m-%d')
                date_groups[date_key].append(email_data)

        processed_emails = []
        duplicate_count = 0

        for date_key, emails in date_groups.items():
            if len(emails) == 1:
                # 单个邮件，直接添加
                processed_emails.append(emails[0])
            else:
                # 多个邮件，保留勤奋时间最长的那个
                duplicate_count += len(emails) - 1
                
                # 定义辅助函数计算勤奋时间
                def get_diligence_duration(content):
                    try:
                        pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
                        matches = re.findall(pattern, content)
                        total_minutes = 0
                        for start, end in matches:
                            h1, m1 = map(int, start.split(':'))
                            h2, m2 = map(int, end.split(':'))
                            start_mins = h1 * 60 + m1
                            end_mins = h2 * 60 + m2
                            if end_mins < start_mins:
                                end_mins += 24 * 60
                            total_minutes += (end_mins - start_mins)
                        return total_minutes
                    except:
                        return 0

                # 找出勤奋时间最长的邮件
                best_email = max(emails, key=lambda e: get_diligence_duration(e.content))
                
                # 如果都没有勤奋时间，退化为保留内容最长的
                if get_diligence_duration(best_email.content) == 0:
                     best_email = max(emails, key=lambda e: len(e.content))

                # 更新文件名为合并样式，以便知道来源（可选，或者保持原名）
                # 这里我们保持原名或者标记为合并，用户之前说“不是保留正文内容最长的，而是保留勤奋时间更长的”
                # 意味着他只想要那一封。我们可以修改文件名提示这是经过选择的
                # 但为了文件名简洁，我们还是用 best_email 的原始信息，或者只修改文件名为 include all filenames
                
                # 记录一下被保留的文件
                logger.info(f"日期 {date_key} 有 {len(emails)} 封邮件，保留了勤奋时间最长的: {best_email.filename}")
                
                processed_emails.append(best_email)

        if duplicate_count > 0:
            logger.info(f"共去重处理了 {duplicate_count} 个重复邮件")

        return processed_emails

    # _merge_duplicate_emails 方法不再需要，可以删除或保留但不再调用
    def _merge_duplicate_emails(self, emails: List[EmailData]) -> EmailData:
        """已弃用"""
        return emails[0]

    def process_emails_for_months(self, selected_months: List[str]) -> bool:
        """
        处理指定月份的邮件

        Args:
            selected_months: 选择的月份列表，格式如 ['2024-07', '2024-08']

        Returns:
            处理是否成功
        """
        try:
            logger.info(f"开始处理指定月份的邮件: {selected_months}")

            # 扫描邮件文件
            email_files = self._scan_email_files()
            if not email_files:
                logger.warning("未找到任何邮件文件")
                return False

            logger.info(f"找到 {len(email_files)} 个邮件文件")

            # 解析邮件文件
            email_data_list = self._parse_email_files(email_files)
            if not email_data_list:
                logger.error("没有成功解析任何邮件文件")
                return False

            logger.info(f"成功解析 {len(email_data_list)} 个邮件文件")

            # 过滤指定月份的邮件
            filtered_emails = self._filter_emails_by_months(email_data_list, selected_months)
            if not filtered_emails:
                logger.warning("指定月份中没有找到邮件")
                return False

            logger.info(f"过滤后得到 {len(filtered_emails)} 个指定月份的邮件")

            # 生成报告
            success = self._generate_and_save_reports(filtered_emails)

            if success:
                logger.info("指定月份邮件处理完成")
                return True
            else:
                logger.error("报告生成失败")
                return False

        except Exception as e:
            logger.error(f"处理指定月份邮件时发生错误: {e}")
            return False

    def _filter_emails_by_months(self, email_data_list: List[EmailData], selected_months: List[str]) -> List[EmailData]:
        """
        按月份过滤邮件

        Args:
            email_data_list: 邮件数据列表
            selected_months: 选择的月份列表

        Returns:
            过滤后的邮件列表
        """
        filtered_emails = []

        for email_data in email_data_list:
            if email_data.date:
                email_month = email_data.date.strftime('%Y-%m')
                if email_month in selected_months:
                    filtered_emails.append(email_data)

        return filtered_emails
    
    def _generate_and_save_reports(self, email_data_list: List[EmailData]) -> bool:
        """
        生成并保存报告
        
        Args:
            email_data_list: 邮件数据列表
            
        Returns:
            是否成功
        """
        try:
            # 生成月度报告
            monthly_reports = self.report_generator.generate_monthly_reports(email_data_list)
            if not monthly_reports:
                logger.error("生成月度报告失败")
                return False
            
            # 保存月度报告
            saved_files = self.report_generator.save_reports(monthly_reports)
            if not saved_files:
                logger.error("保存月度报告失败")
                return False
            
            # 生成汇总报告
            summary_content = self.report_generator.generate_summary_report(email_data_list)
            summary_reports = {"工作总结汇总报告.md": summary_content}
            
            # 保存汇总报告
            summary_files = self.report_generator.save_reports(summary_reports)
            
            # 输出结果信息
            self._print_results(saved_files + summary_files, email_data_list)
            
            return True
            
        except Exception as e:
            logger.error(f"生成和保存报告时发生错误: {e}")
            return False
    
    def _print_results(self, saved_files: List[Path], email_data_list: List[EmailData]):
        """
        打印处理结果
        
        Args:
            saved_files: 保存的文件列表
            email_data_list: 邮件数据列表
        """
        print("\n" + "="*60)
        print("📊 处理结果汇总")
        print("="*60)
        print(f"✅ 成功处理邮件: {len(email_data_list)} 封")
        print(f"📁 生成报告文件: {len(saved_files)} 个")
        print(f"📂 输出目录: {config.OUTPUT_DIR}")
        print("\n📋 生成的报告文件:")
        
        for file_path in saved_files:
            file_size = file_path.stat().st_size
            print(f"   📄 {file_path.name} ({file_size:,} 字节)")
        
        print("\n" + "="*60)
        print("🎉 处理完成！")
        print("="*60)
    
    def get_statistics(self) -> dict:
        """
        获取处理统计信息
        
        Returns:
            统计信息字典
        """
        try:
            email_files = self._scan_email_files()
            email_data_list = []
            
            for file_path in email_files:
                email_data = self.email_parser.parse_email_file(file_path)
                if email_data:
                    email_data_list.append(email_data)
            
            # 按月份分组统计
            monthly_stats = {}
            for email_data in email_data_list:
                if email_data.date:
                    month_key = f"{email_data.date.year}-{email_data.date.month:02d}"
                    if month_key not in monthly_stats:
                        monthly_stats[month_key] = 0
                    monthly_stats[month_key] += 1
            
            return {
                "total_files": len(email_files),
                "parsed_emails": len(email_data_list),
                "monthly_stats": monthly_stats,
                "date_range": {
                    "start": min(email_data_list, key=lambda x: x.date).date if email_data_list else None,
                    "end": max(email_data_list, key=lambda x: x.date).date if email_data_list else None
                }
            }
            
        except Exception as e:
            logger.error(f"获取统计信息时发生错误: {e}")
            return {}
