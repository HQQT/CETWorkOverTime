"""
数据库连接管理模块

提供 MySQL 连接池管理和按年分表路由功能。
"""

import logging
from typing import Optional

import pymysql
from dbutils.pooled_db import PooledDB

import config

logger = logging.getLogger(__name__)

# 全局连接池（延迟初始化）
_pool: Optional[PooledDB] = None


def _create_pool() -> PooledDB:
    """创建数据库连接池"""
    return PooledDB(
        creator=pymysql,
        maxconnections=10,
        mincached=2,
        maxcached=5,
        blocking=True,
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset=config.DB_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_connection():
    """
    从连接池获取一个数据库连接

    Returns:
        pymysql 连接对象（用完后应调用 .close() 归还连接池）
    """
    global _pool
    if _pool is None:
        _pool = _create_pool()
        logger.info(f"数据库连接池已创建: {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    return _pool.connection()


def get_table_name(year: int) -> str:
    """
    根据年份返回对应的分表名称

    Args:
        year: 年份，如 2024

    Returns:
        表名，如 'email_2024'
    """
    return f"email_{year}"


# ---- 年份表的 DDL 模板 ----
_CREATE_YEAR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    email_date      DATE NOT NULL COMMENT '邮件日期（工作日）',
    subject         VARCHAR(500) NOT NULL DEFAULT '' COMMENT '邮件主题',
    sender          VARCHAR(200) NOT NULL DEFAULT '' COMMENT '发件人',
    content         TEXT NOT NULL COMMENT '邮件正文（已清洗）',
    raw_content     MEDIUMTEXT COMMENT '邮件原始正文',
    diligence_start TIME DEFAULT NULL COMMENT '勤奋时间-开始',
    diligence_end   TIME DEFAULT NULL COMMENT '勤奋时间-结束',
    diligence_hours DECIMAL(5,2) DEFAULT 0 COMMENT '勤奋时长(小时)',
    message_id      VARCHAR(500) DEFAULT '' COMMENT 'Message-ID 去重',
    source_filename VARCHAR(500) DEFAULT '' COMMENT '来源 .eml 文件名',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_email_date (email_date),
    INDEX idx_message_id (message_id),
    INDEX idx_year_month (email_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='邮件工作日志-{year}年';
"""

_CREATE_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS email_meta (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    meta_key        VARCHAR(100) NOT NULL UNIQUE COMMENT '配置键',
    meta_value      TEXT COMMENT '配置值',
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统元数据(缓存、配置等)';
"""

# 已确认存在的年份表缓存（避免每次都执行 CREATE TABLE IF NOT EXISTS）
_ensured_tables: set = set()


def ensure_meta_table():
    """确保 email_meta 元数据表存在"""
    if '_meta' in _ensured_tables:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_META_TABLE_SQL)
        _ensured_tables.add('_meta')
        logger.debug("email_meta 表已就绪")
    finally:
        conn.close()


def ensure_year_table(year: int):
    """
    确保指定年份的邮件表存在，不存在则自动建表

    Args:
        year: 年份
    """
    table_name = get_table_name(year)
    if table_name in _ensured_tables:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = _CREATE_YEAR_TABLE_SQL.format(table_name=table_name, year=year)
            cur.execute(sql)
        _ensured_tables.add(table_name)
        logger.info(f"年份表 {table_name} 已就绪")
    finally:
        conn.close()


def init_db():
    """
    初始化数据库：创建元数据表和当前年份的邮件表

    应用启动时调用一次。
    """
    from datetime import datetime

    ensure_meta_table()
    current_year = datetime.now().year
    ensure_year_table(current_year)
    logger.info(f"数据库初始化完成，当前年份表: email_{current_year}")


def close_pool():
    """关闭连接池（应用退出时调用）"""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("数据库连接池已关闭")
