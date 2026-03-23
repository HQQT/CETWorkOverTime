"""
配置文件 - 邮件工作总结汇总程序
"""

import os
from pathlib import Path

# 加载 .env 文件中的环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass  # dotenv 未安装时跳过，直接使用系统环境变量

# 基础配置
BASE_DIR = Path(__file__).parent
WORK_SUMMARY_DIR = BASE_DIR / os.getenv("WORK_SUMMARY_DIR", "工作总结")
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "output")

# 邮件文件配置
EMAIL_FILE_EXTENSION = os.getenv("EMAIL_FILE_EXTENSION", ".eml")
EMAIL_FILE_PATTERNS = [
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]\(不够300字\)\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]_迟发补登\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]\(不够300字\)\(\d+\)\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]\(\d+\)\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]_迟发补登\(不够300字\)\.eml$",
    r"--工作日志\[(\d{4}-\d{1,2}-\d{1,2})\]--\[提交成功\]_迟发补登\(不够300字\)\(\d+\)\.eml$",
]

# 排除的文件模式（回复邮件等）
EXCLUDE_PATTERNS = [
    r"^回复_.*\.eml$",
]

# 编码配置
DEFAULT_ENCODING = os.getenv("DEFAULT_ENCODING", "gb2312")
FALLBACK_ENCODINGS = os.getenv("FALLBACK_ENCODINGS", "utf-8,gbk,gb18030").split(",")

# 输出配置
OUTPUT_FORMAT = os.getenv("OUTPUT_FORMAT", "markdown")
CACHE_FILENAME = os.getenv("CACHE_FILENAME", ".process_cache.json")
DATE_FORMAT = "%Y年%m月"
REPORT_FILENAME_FORMAT = "{year}年{month:02d}月工作总结.md"

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 邮件内容提取配置
CONTENT_START_MARKERS = [
    "工作总结",
    "今日工作",
    "工作内容",
]

CONTENT_END_MARKERS = [
    "[点击查看详细的工作计划请点击查看]",
    "工作计划",
    "明日计划",
]

# 创建输出目录
OUTPUT_DIR.mkdir(exist_ok=True)

# ============ IMAP 邮箱获取配置 ============
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.exmail.qq.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USE_SSL = os.getenv("IMAP_USE_SSL", "true").lower() in ("true", "1", "yes")
IMAP_USERNAME = os.getenv("EMAIL_USERNAME", "")
IMAP_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # IMAP 授权码
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "&XeVPXGXlX9c-")  # 工作日志 文件夹
IMAP_SEARCH_SUBJECT = os.getenv("IMAP_SEARCH_SUBJECT", "--工作日志")  # 搜索邮件主题关键词
IMAP_SEARCH_DAYS = int(os.getenv("IMAP_SEARCH_DAYS", "365"))

# ============ MySQL 数据库配置 ============
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "cetworkovertime")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")
