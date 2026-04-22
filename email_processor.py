"""
邮件处理器模块
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set
import sys

import config
from diligence_time import sum_diligence_minutes
from email_parser import EmailParser, EmailData
from report_generator import ReportGenerator
from date_utils import DateUtils

logger = logging.getLogger(__name__)

# 延迟导入数据库模块（仅在数据库可用时使用）
def _get_repository():
    """获取 email_repository 模块（延迟导入避免数据库未配置时报错）"""
    try:
        import email_repository
        return email_repository
    except Exception as e:
        logger.debug(f"数据库模块不可用: {e}")
        return None


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
        
        self.cache_path = config.OUTPUT_DIR / config.CACHE_FILENAME
        
        logger.info(f"邮件处理器初始化完成，工作目录: {self.work_dir}")
    
    # ============ 缓存管理 ============
    
    def _load_cache(self) -> dict:
        """
        加载处理缓存
        
        Returns:
            缓存字典
        """
        try:
            if self.cache_path.exists():
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                logger.info(f"已加载缓存，包含 {len(cache.get('processed_files', {}))} 个文件记录")
                return cache
        except Exception as e:
            logger.warning(f"加载缓存失败，将全量处理: {e}")
        
        return {"version": 1, "processed_files": {}}
    
    def _save_cache(self, cache: dict):
        """
        保存处理缓存
        
        Args:
            cache: 缓存字典
        """
        try:
            config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            logger.info(f"缓存已保存到 {self.cache_path}")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def _get_changed_files(self, email_files: List[Path], cache: dict) -> tuple:
        """
        对比缓存，找出新增/修改/删除的文件
        
        Args:
            email_files: 当前扫描到的邮件文件列表
            cache: 缓存数据
            
        Returns:
            (changed_files, deleted_filenames, unchanged_filenames)
        """
        processed = cache.get('processed_files', {})
        current_filenames = {f.name for f in email_files}
        
        changed_files = []
        unchanged_filenames = set()
        
        for file_path in email_files:
            fname = file_path.name
            current_mtime = os.path.getmtime(file_path)
            
            if fname in processed:
                cached_mtime = processed[fname].get('mtime', 0)
                if abs(current_mtime - cached_mtime) < 1.0:  # 时间精度容差
                    unchanged_filenames.add(fname)
                    continue
            
            # 新文件或已修改的文件
            changed_files.append(file_path)
        
        # 找出已删除的文件
        deleted_filenames = set(processed.keys()) - current_filenames
        
        logger.info(
            f"增量检测结果: 新增/修改 {len(changed_files)} 个, "
            f"未变更 {len(unchanged_filenames)} 个, "
            f"已删除 {len(deleted_filenames)} 个"
        )
        
        return changed_files, deleted_filenames, unchanged_filenames
    
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

                # 找出勤奋时间最长的邮件
                best_email = max(emails, key=lambda e: sum_diligence_minutes(e.content))
                
                # 如果都没有勤奋时间，退化为保留内容最长的
                if sum_diligence_minutes(best_email.content) == 0:
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

    def process_emails_for_months(self, selected_months: Optional[List[str]] = None, incremental: bool = False) -> bool:
        """
        处理指定月份的邮件

        Args:
            selected_months: 选择的月份列表，None 表示所有月份
            incremental: 是否启用增量模式

        Returns:
            处理是否成功
        """
        try:
            logger.info(f"开始处理指定月份的邮件: {selected_months}, 增量模式: {incremental}")

            # 扫描邮件文件
            email_files = self._scan_email_files()
            if not email_files:
                logger.warning("未找到任何邮件文件")
                return False

            logger.info(f"找到 {len(email_files)} 个邮件文件")

            if incremental:
                return self._process_incremental(email_files, selected_months)
            else:
                return self._process_full(email_files, selected_months)

        except Exception as e:
            logger.error(f"处理指定月份邮件时发生错误: {e}")
            return False
    
    def _process_full(self, email_files: List[Path], selected_months: List[str]) -> bool:
        """
        全量处理邮件
        """
        # 解析邮件文件
        email_data_list = self._parse_email_files(email_files)
        if not email_data_list:
            logger.error("没有成功解析任何邮件文件")
            return False

        logger.info(f"成功解析 {len(email_data_list)} 个邮件文件")

        # ====== 入库到 PostgreSQL ======
        self._save_to_database(email_data_list)

        # 过滤指定月份的邮件
        filtered_emails = self._filter_emails_by_months(email_data_list, selected_months)
        if not filtered_emails:
            logger.warning("指定月份中没有找到邮件")
            return False

        logger.info(f"过滤后得到 {len(filtered_emails)} 个指定月份的邮件")

        # 生成报告
        success = self._generate_and_save_reports(filtered_emails)

        if success:
            # 全量处理后更新缓存
            self._update_cache_after_processing(email_data_list, email_files)
            logger.info("全量处理完成")
            return True
        else:
            logger.error("报告生成失败")
            return False
    
    def _process_incremental(self, email_files: List[Path], selected_months: List[str]) -> bool:
        """
        增量处理邮件
        """
        cache = self._load_cache()
        
        # 检测变更
        changed_files, deleted_filenames, unchanged_filenames = self._get_changed_files(email_files, cache)
        
        # 没有任何变化
        if not changed_files and not deleted_filenames:
            print("\n✅ 没有检测到变更，无需重新处理")
            logger.info("增量检测: 无变更，跳过处理")
            return True
        
        # 解析变更的文件，确定受影响的月份
        affected_months: Set[str] = set()
        
        # 处理变更文件
        changed_email_data = []
        if changed_files:
            changed_email_data = self._parse_email_files(changed_files)
            for ed in changed_email_data:
                if ed.date:
                    affected_months.add(ed.date.strftime('%Y-%m'))
        
        # 处理已删除的文件（它们之前属于哪些月份）
        processed = cache.get('processed_files', {})
        for fname in deleted_filenames:
            month = processed[fname].get('month', '')
            if month:
                affected_months.add(month)
                logger.info(f"已删除文件 {fname} 影响月份 {month}")
        
        # 只保留用户选择的月份（selected_months 为 None 表示所有月份）
        if selected_months is not None:
            affected_months = affected_months & set(selected_months)
        
        if not affected_months:
            print("\n✅ 选定月份内没有变更，无需重新处理")
            # 但仍然需要更新缓存（可能有变更但不在选定月份内）
            self._update_cache_after_processing(changed_email_data, changed_files, cache)
            return True
        
        print(f"\n🔄 增量处理: 检测到 {len(changed_files)} 个变更文件, {len(deleted_filenames)} 个删除文件")
        print(f"   受影响月份: {', '.join(sorted(affected_months))}")
        
        # 对受影响的月份，重新解析所有相关文件（包括未变更的）
        # 获取受影响月份对应的所有文件
        month_files = []
        for file_path in email_files:
            date = self.date_utils.extract_date_from_filename(file_path.name)
            if date and date.strftime('%Y-%m') in affected_months:
                month_files.append(file_path)
        
        logger.info(f"需要重新解析受影响月份的 {len(month_files)} 个文件")
        
        # 解析这些文件
        email_data_list = self._parse_email_files(month_files)
        if not email_data_list:
            logger.warning("受影响月份中没有解析到有效邮件")
            # 可能是该月份的文件全部删除了，仍算成功
            self._update_cache_after_processing([], email_files, cache)
            return True

        # ====== 入库到 PostgreSQL ======
        self._save_to_database(email_data_list)

        # 生成受影响月份的报告
        filtered_emails = self._filter_emails_by_months(email_data_list, list(affected_months))
        success = self._generate_and_save_reports(filtered_emails)
        
        if success:
            # 更新缓存
            self._update_cache_after_processing([], email_files, cache)
            logger.info(f"增量处理完成，更新了 {len(affected_months)} 个月份的报告")
            return True
        else:
            logger.error("增量报告生成失败")
            return False
    
    def _update_cache_after_processing(self, email_data_list: List[EmailData] = None, 
                                        email_files: List[Path] = None,
                                        cache: dict = None):
        """
        处理完成后更新缓存
        
        Args:
            email_data_list: 已解析的邮件数据（可选，用于获取月份信息）
            email_files: 所有当前邮件文件
            cache: 现有缓存（如果为 None，创建新缓存）
        """
        if cache is None:
            cache = {"version": 1, "processed_files": {}}
        
        processed = cache.get('processed_files', {})
        
        if email_files:
            current_filenames = {f.name for f in email_files}
            
            # 移除已删除的文件
            for fname in list(processed.keys()):
                if fname not in current_filenames:
                    del processed[fname]
            
            # 更新所有当前文件的信息
            for file_path in email_files:
                fname = file_path.name
                mtime = os.path.getmtime(file_path)
                date = self.date_utils.extract_date_from_filename(fname)
                month = date.strftime('%Y-%m') if date else ''
                processed[fname] = {
                    'mtime': mtime,
                    'month': month
                }
        
        cache['processed_files'] = processed
        self._save_cache(cache)

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

    # ============ 数据库集成 ============

    def _save_to_database(self, email_data_list: List[EmailData]):
        """
        将解析后的邮件数据批量保存到 PostgreSQL

        如果数据库模块不可用则静默跳过。
        """
        repo = _get_repository()
        if repo is None:
            return

        try:
            stats = repo.bulk_save_emails(email_data_list)
            saved = stats.get('saved', 0)
            skipped = stats.get('skipped', 0)
            failed = stats.get('failed', 0)
            if saved > 0 or failed > 0:
                print(f"\n💾 数据库入库: 新增 {saved}, 跳过 {skipped}, 失败 {failed}")
            logger.info(f"数据库入库完成: {stats}")
        except Exception as e:
            logger.error(f"数据库入库失败（不影响报告生成）: {e}")
            print(f"\n⚠️ 数据库入库失败（不影响报告生成）: {e}")

    def sync_to_db(self) -> dict:
        """
        一次性将所有本地 .eml 文件入库（历史数据迁移）

        Returns:
            {'saved': int, 'skipped': int, 'failed': int}
        """
        repo = _get_repository()
        if repo is None:
            raise RuntimeError("数据库模块不可用，请检查 PostgreSQL 配置")

        logger.info("开始历史数据同步到数据库")
        email_files = self._scan_email_files()
        if not email_files:
            logger.warning("未找到任何邮件文件")
            return {'saved': 0, 'skipped': 0, 'failed': 0}

        email_data_list = self._parse_email_files(email_files)
        stats = repo.bulk_save_emails(email_data_list)
        logger.info(f"历史数据同步完成: {stats}")
        return stats
