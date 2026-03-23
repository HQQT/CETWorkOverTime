"""
数据库连接管理模块

提供 PostgreSQL 连接池管理和单表 Schema 初始化功能。
"""

import logging
from typing import Any, Optional, TYPE_CHECKING

import config

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

EMAILS_TABLE_NAME = "emails"
META_TABLE_NAME = "email_meta"

_CREATE_EMAILS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS emails (
    id              BIGSERIAL PRIMARY KEY,
    email_date      DATE NOT NULL UNIQUE,
    subject         VARCHAR(500) NOT NULL DEFAULT '',
    sender          VARCHAR(200) NOT NULL DEFAULT '',
    content         TEXT NOT NULL,
    raw_content     TEXT,
    diligence_start TIME DEFAULT NULL,
    diligence_end   TIME DEFAULT NULL,
    diligence_hours NUMERIC(5, 2) DEFAULT 0,
    message_id      VARCHAR(500) DEFAULT '',
    source_filename VARCHAR(500) DEFAULT '',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_EMAILS_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails (message_id)",
    "CREATE INDEX IF NOT EXISTS idx_emails_email_date ON emails (email_date)",
]

_CREATE_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS email_meta (
    id          BIGSERIAL PRIMARY KEY,
    meta_key    VARCHAR(100) NOT NULL UNIQUE,
    meta_value  TEXT,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# 全局连接池（延迟初始化）
_pool: Optional["ConnectionPool"] = None
_tables_ready = False


def _load_postgres_modules():
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    return psycopg, dict_row, ConnectionPool


def _build_conninfo(dbname: Optional[str] = None) -> str:
    parts = [
        f"host={config.DB_HOST}",
        f"port={config.DB_PORT}",
        f"user={config.DB_USER}",
        f"password={config.DB_PASSWORD}",
        f"dbname={dbname or config.DB_NAME}",
    ]
    return " ".join(parts)


class _PooledConnection:
    """将 psycopg_pool.getconn() 返回的连接包装成现有代码可用的 close() 语义。"""

    def __init__(self, pool: "ConnectionPool", conn: Any):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def close(self):
        if self._conn is not None:
            self._pool.putconn(self._conn)
            self._conn = None


def _create_pool():
    """创建 PostgreSQL 连接池。"""
    _, dict_row, ConnectionPool = _load_postgres_modules()
    return ConnectionPool(
        conninfo=_build_conninfo(),
        min_size=2,
        max_size=10,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
    )


def get_connection():
    """
    从连接池获取一个数据库连接。

    Returns:
        可直接 `.close()` 归还连接池的 psycopg 连接包装对象
    """
    global _pool
    if _pool is None:
        _pool = _create_pool()
        logger.info(f"PostgreSQL 连接池已创建: {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    return _PooledConnection(_pool, _pool.getconn())


def get_table_name(year: int) -> str:
    """
    保留原接口，统一返回 PostgreSQL 单表名。

    Args:
        year: 年份（已忽略，仅为兼容旧调用方）
    """
    return EMAILS_TABLE_NAME


def ensure_tables():
    """确保 PostgreSQL 单表结构已创建。"""
    global _tables_ready
    if _tables_ready:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_META_TABLE_SQL)
            cur.execute(_CREATE_EMAILS_TABLE_SQL)
            for sql in _CREATE_EMAILS_INDEXES_SQL:
                cur.execute(sql)
        _tables_ready = True
        logger.info("PostgreSQL 表结构已就绪")
    finally:
        conn.close()


def ensure_meta_table():
    """兼容旧调用方：确保核心表存在。"""
    ensure_tables()


def ensure_year_table(year: int):
    """兼容旧调用方：PostgreSQL 单表模式下不再按年建表。"""
    ensure_tables()


def _database_exists(conn, db_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def init_db():
    """
    初始化数据库：自动创建数据库（如不存在）并创建业务表。

    应用启动时调用一次。
    """
    global _pool, _tables_ready

    psycopg, dict_row, _ = _load_postgres_modules()

    try:
        admin_conn = psycopg.connect(
            _build_conninfo("postgres"),
            autocommit=True,
            row_factory=dict_row,
        )
        try:
            if not _database_exists(admin_conn, config.DB_NAME):
                with admin_conn.cursor() as cur:
                    cur.execute(f"CREATE DATABASE {_quote_identifier(config.DB_NAME)}")
                logger.info(f"数据库 {config.DB_NAME} 已创建")
            else:
                logger.info(f"数据库 {config.DB_NAME} 已就绪")
        finally:
            admin_conn.close()
    except Exception as e:
        logger.warning(f"自动创建 PostgreSQL 数据库失败（可能已存在或权限不足）: {e}")

    # 重新创建连接池，确保指向最新数据库
    close_pool()
    _tables_ready = False
    ensure_tables()
    logger.info("PostgreSQL 数据库初始化完成")


def close_pool():
    """关闭连接池（应用退出时调用）。"""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("PostgreSQL 连接池已关闭")
