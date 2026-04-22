"""
邮件数据访问层（Repository 模式）

封装所有 PostgreSQL CRUD 操作，对上层屏蔽单表细节。
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from db import ensure_meta_table, ensure_year_table, get_connection, get_table_name
from diligence_time import extract_last_diligence_record

logger = logging.getLogger(__name__)


def _table_name_for_date(email_date: date) -> str:
    """兼容旧调用链，统一返回 PostgreSQL 单表名。"""
    ensure_year_table(email_date.year)
    return get_table_name(email_date.year)


def _month_date_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


# ==================== 勤奋时间解析工具 ====================

def _parse_diligence_time(content: str) -> dict:
    """
    从邮件正文中提取勤奋时间

    Args:
        content: 邮件正文

    Returns:
        {'start': 'HH:MM', 'end': 'HH:MM', 'hours': float} 或空字典
    """
    return extract_last_diligence_record(content)


# ==================== 邮件 CRUD ====================

def save_email(email_date: date,
               subject: str = '',
               sender: str = '',
               content: str = '',
               raw_content: str = '',
               message_id: str = '',
               source_filename: str = '') -> Optional[int]:
    """
    保存一封邮件到 PostgreSQL 单表（INSERT 或 UPDATE）。

    如果该日期已存在记录，则比较勤奋时长：
    - 新邮件勤奋时间更长 → 覆盖
    - 否则 → 跳过

    Returns:
        记录 ID，跳过则返回 None
    """
    table = _table_name_for_date(email_date)
    diligence = _parse_diligence_time(content)
    d_start = diligence.get('start')
    d_end = diligence.get('end')
    d_hours = diligence.get('hours', 0)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, diligence_hours FROM {table} WHERE email_date = %s",
                (email_date,),
            )
            existing = cur.fetchone()

            if existing:
                if d_hours <= (existing.get('diligence_hours') or 0):
                    logger.debug(f"跳过 {email_date}: 现有勤奋时间更长")
                    return None

                cur.execute(f"""
                    UPDATE {table}
                    SET subject = %s,
                        sender = %s,
                        content = %s,
                        raw_content = %s,
                        diligence_start = %s,
                        diligence_end = %s,
                        diligence_hours = %s,
                        message_id = %s,
                        source_filename = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id
                """, (
                    subject, sender, content, raw_content,
                    d_start, d_end, d_hours,
                    message_id, source_filename,
                    existing['id'],
                ))
                row = cur.fetchone()
                logger.info(f"更新 {email_date}: 勤奋时间更长，已覆盖")
                return row['id'] if row else existing['id']

            cur.execute(f"""
                INSERT INTO {table}
                    (email_date, subject, sender, content, raw_content,
                     diligence_start, diligence_end, diligence_hours,
                     message_id, source_filename)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                email_date, subject, sender, content, raw_content,
                d_start, d_end, d_hours,
                message_id, source_filename,
            ))
            row = cur.fetchone()
            new_id = row['id'] if row else None
            logger.info(f"新增邮件: {email_date}, id={new_id}")
            return new_id
    except Exception as e:
        logger.error(f"保存邮件失败 ({email_date}): {e}")
        raise
    finally:
        conn.close()


def bulk_save_emails(email_data_list) -> dict:
    """
    批量保存邮件（逐条调用 save_email）。
    """
    stats = {'saved': 0, 'skipped': 0, 'failed': 0}

    for email_data in email_data_list:
        try:
            if not email_data.date:
                stats['skipped'] += 1
                continue

            result = save_email(
                email_date=email_data.date.date() if isinstance(email_data.date, datetime) else email_data.date,
                subject=email_data.subject or '',
                sender=email_data.sender or '',
                content=email_data.content or '',
                raw_content=email_data.raw_content or '',
                message_id='',
                source_filename=email_data.filename or '',
            )
            if result is not None:
                stats['saved'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"批量入库失败 ({email_data.filename}): {e}")
            stats['failed'] += 1

    logger.info(f"批量入库完成: {stats}")
    return stats


# ==================== 查询 ====================

def get_emails_by_month(year: int, month: int) -> List[Dict[str, Any]]:
    """
    查询指定月份的所有邮件。
    """
    table = _table_name_for_date(date(year, month, 1))
    start_date, end_date = _month_date_range(year, month)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM {table}
                WHERE email_date >= %s AND email_date < %s
                ORDER BY email_date
                """,
                (start_date, end_date),
            )
            rows = cur.fetchall()
            return [_serialize_row(r) for r in rows]
    finally:
        conn.close()


def get_emails_by_date_range(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    按日期范围查询邮件。
    """
    table = _table_name_for_date(start_date)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE email_date BETWEEN %s AND %s ORDER BY email_date",
                (start_date, end_date),
            )
            rows = cur.fetchall()
            return [_serialize_row(r) for r in rows]
    finally:
        conn.close()


def get_email_by_date(email_date: date) -> Optional[Dict[str, Any]]:
    """
    查询单日邮件。
    """
    table = _table_name_for_date(email_date)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE email_date = %s",
                (email_date,),
            )
            row = cur.fetchone()
            return _serialize_row(row) if row else None
    finally:
        conn.close()


def get_diligence_stats(year: int) -> Dict[str, Any]:
    """
    获取指定年份的勤奋时间统计。
    """
    import os

    target_hours = float(os.environ.get("DILIGENCE_TARGET_HOURS", "36"))
    table = _table_name_for_date(date(year, 1, 1))
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT EXTRACT(MONTH FROM email_date)::int AS m,
                       COALESCE(SUM(diligence_hours), 0) AS total_hours,
                       COUNT(*) AS entries
                FROM {table}
                WHERE email_date >= %s
                  AND email_date < %s
                  AND diligence_hours > 0
                GROUP BY EXTRACT(MONTH FROM email_date)
                ORDER BY m
            """, (year_start, year_end))
            rows = cur.fetchall()

        months = []
        total_hours = 0.0
        total_target = 0.0
        for row in rows:
            month_value = int(row['m'])
            hours = float(row['total_hours'])
            entries = int(row['entries'])
            months.append({
                'month': month_value,
                'hours': round(hours, 2),
                'entries': entries,
                'target': target_hours,
                'delta': round(hours - target_hours, 2),
            })
            total_hours += hours
            total_target += target_hours

        return {
            'year': year,
            'months': months,
            'total_hours': round(total_hours, 2),
            'total_target': round(total_target, 2),
            'total_delta': round(total_hours - total_target, 2),
        }
    finally:
        conn.close()


def get_all_years() -> List[int]:
    """
    获取数据库中存在邮件数据的所有年份。
    """
    table = _table_name_for_date(date.today())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT DISTINCT EXTRACT(YEAR FROM email_date)::int AS year
                FROM {table}
                ORDER BY year
            """)
            rows = cur.fetchall()
        return [int(row['year']) for row in rows]
    finally:
        conn.close()


def recalculate_diligence_fields(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, int]:
    """
    Recalculate derived diligence fields from stored content.
    """
    table = _table_name_for_date(start_date or end_date or date.today())
    select_sql = f"SELECT id, email_date, content FROM {table}"
    params = None

    if start_date and end_date:
        select_sql += " WHERE email_date BETWEEN %s AND %s"
        params = (start_date, end_date)
    elif start_date:
        select_sql += " WHERE email_date >= %s"
        params = (start_date,)
    elif end_date:
        select_sql += " WHERE email_date <= %s"
        params = (end_date,)

    select_sql += " ORDER BY email_date"

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(select_sql, params)
            rows = cur.fetchall()

            updated = 0
            for row in rows:
                diligence = _parse_diligence_time(row.get("content") or "")
                cur.execute(
                    f"""
                    UPDATE {table}
                    SET diligence_start = %s,
                        diligence_end = %s,
                        diligence_hours = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        diligence.get("start"),
                        diligence.get("end"),
                        diligence.get("hours", 0),
                        row["id"],
                    ),
                )
                updated += 1

        return {"scanned": len(rows), "updated": updated}
    finally:
        conn.close()


def email_exists_by_date(email_date: date) -> bool:
    """检查指定日期是否已有邮件。"""
    return get_email_by_date(email_date) is not None


# ==================== 元数据操作 ====================

def save_meta(key: str, value: str):
    """
    保存元数据（UPSERT）。
    """
    ensure_meta_table()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_meta (meta_key, meta_value)
                VALUES (%s, %s)
                ON CONFLICT (meta_key) DO UPDATE
                SET meta_value = EXCLUDED.meta_value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
        logger.debug(f"元数据已保存: {key}")
    finally:
        conn.close()


def get_meta(key: str) -> Optional[str]:
    """
    获取元数据。
    """
    ensure_meta_table()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meta_value FROM email_meta WHERE meta_key = %s",
                (key,),
            )
            row = cur.fetchone()
            return row['meta_value'] if row else None
    finally:
        conn.close()


def delete_meta(key: str):
    """删除元数据。"""
    ensure_meta_table()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM email_meta WHERE meta_key = %s", (key,))
    finally:
        conn.close()


# ==================== 辅助函数 ====================

def _serialize_row(row: dict) -> dict:
    """
    将数据库行中的特殊类型转为可 JSON 序列化的类型。
    """
    if not row:
        return row

    import decimal
    from datetime import date as date_type, datetime as dt_type, time as time_type

    result = {}
    for key, value in row.items():
        if isinstance(value, (date_type, dt_type)):
            result[key] = value.isoformat()
        elif isinstance(value, time_type):
            result[key] = value.strftime("%H:%M")
        elif isinstance(value, timedelta):
            total_seconds = int(value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            result[key] = f"{hours:02d}:{minutes:02d}"
        elif isinstance(value, decimal.Decimal):
            result[key] = float(value)
        else:
            result[key] = value

    return result
