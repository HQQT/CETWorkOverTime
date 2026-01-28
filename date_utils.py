"""
日期处理工具模块
"""

import re
import logging
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path

import config

logger = logging.getLogger(__name__)


class DateUtils:
    """日期处理工具类"""
    
    @staticmethod
    def extract_date_from_filename(filename: str) -> Optional[datetime]:
        """
        从文件名中提取日期
        
        Args:
            filename: 邮件文件名
            
        Returns:
            datetime对象，如果提取失败返回None
        """
        try:
            # 尝试匹配各种文件名模式
            for pattern in config.EMAIL_FILE_PATTERNS:
                match = re.search(pattern, filename)
                if match:
                    date_str = match.group(1)
                    # 解析日期字符串 YYYY-M-D 或 YYYY-MM-DD
                    return DateUtils._parse_date_string(date_str)
            
            logger.warning(f"无法从文件名提取日期: {filename}")
            return None
            
        except Exception as e:
            logger.error(f"提取日期时发生错误: {filename}, 错误: {e}")
            return None
    
    @staticmethod
    def _parse_date_string(date_str: str) -> datetime:
        """
        解析日期字符串
        
        Args:
            date_str: 日期字符串，格式如 "2024-7-1" 或 "2024-07-01"
            
        Returns:
            datetime对象
        """
        # 分割年月日
        parts = date_str.split('-')
        if len(parts) != 3:
            raise ValueError(f"无效的日期格式: {date_str}")
        
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        
        return datetime(year, month, day)
    
    @staticmethod
    def extract_date_from_email_header(email_date: str) -> Optional[datetime]:
        """
        从邮件头的Date字段提取日期
        
        Args:
            email_date: 邮件头中的日期字符串
            
        Returns:
            datetime对象，如果解析失败返回None
        """
        try:
            # 常见的邮件日期格式
            date_formats = [
                "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
                "%a, %d %b %Y %H:%M:%S +0800",
                "%d %b %Y %H:%M:%S +0800",
                "%Y-%m-%d %H:%M:%S",
            ]
            
            for fmt in date_formats:
                try:
                    return datetime.strptime(email_date.strip(), fmt)
                except ValueError:
                    continue
            
            logger.warning(f"无法解析邮件日期: {email_date}")
            return None
            
        except Exception as e:
            logger.error(f"解析邮件日期时发生错误: {email_date}, 错误: {e}")
            return None
    
    @staticmethod
    def get_month_year_key(date: datetime) -> Tuple[int, int]:
        """
        获取年月键值对，用于分组
        
        Args:
            date: datetime对象
            
        Returns:
            (年, 月) 元组
        """
        return (date.year, date.month)
    
    @staticmethod
    def format_month_year(year: int, month: int) -> str:
        """
        格式化年月显示
        
        Args:
            year: 年份
            month: 月份
            
        Returns:
            格式化的年月字符串
        """
        return f"{year}年{month:02d}月"
    
    @staticmethod
    def is_valid_work_date(date: datetime) -> bool:
        """
        检查是否为有效的工作日期（排除未来日期）
        
        Args:
            date: 要检查的日期
            
        Returns:
            是否为有效日期
        """
        now = datetime.now()
        return date <= now
    
    @staticmethod
    def should_exclude_file(filename: str) -> bool:
        """
        检查文件是否应该被排除
        
        Args:
            filename: 文件名
            
        Returns:
            是否应该排除
        """
        for pattern in config.EXCLUDE_PATTERNS:
            if re.search(pattern, filename):
                return True
        return False
