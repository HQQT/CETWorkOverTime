"""
邮件数据访问层（Repository 模式）

封装所有数据库 CRUD 操作，对上层屏蔽分表细节。
"""

import re
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from db import get_connection, get_table_name, ensure_year_table, ensure_meta_table

logger = logging.getLogger(__name__)


# ==================== 勤奋时间解析工具 ====================

def _parse_diligence_time(content: str) -> dict:
    """
    从邮件正文中提取勤奋时间

    Args:
        content: 邮件正文

    Returns:
        {'start': 'HH:MM', 'end': 'HH:MM', 'hours': float} 或空字典
    """
    pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
    matches = re.findall(pattern, content or '')
    if not matches:
        return {}

    # 取最后一条（或唯一一条）
    start_str, end_str = matches[-1]
    sh, sm = map(int, start_str.split(':'))
    eh, em = map(int, end_str.split(':'))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min < start_min:
        end_min += 24 * 60
    hours = round((end_min - start_min) / 60.0, 2)

    return {
        'start': start_str,
        'end': end_str,
        'hours': hours,
    }


# ==================== 邮件 CRUD ====================

def save_email(email_date: date,
               subject: str = '',
               sender: str = '',
               content: str = '',
               raw_content: str = '',
               message_id: str = '',
               source_filename: str = '') -> Optional[int]:
    """
    保存一封邮件到对应年份表（INSERT 或 UPDATE）

    如果该日期已存在记录，则比较勤奋时长：
    - 新邮件勤奋时间更长 → 覆盖
    - 否则 → 跳过

    Args:
        email_date: 邮件日期
        subject: 邮件主题
        sender: 发件人
        content: 清洗后的邮件正文
        raw_content: 原始正文
        message_id: Message-ID
        source_filename: 来源文件名

    Returns:
        记录 ID，跳过则返回 None
    """
    year = email_date.year
    ensure_year_table(year)
    table = get_table_name(year)

    # 解析勤奋时间
    diligence = _parse_diligence_time(content)
    d_start = diligence.get('start')
    d_end = diligence.get('end')
    d_hours = diligence.get('hours', 0)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 检查该日期是否已有记录
            cur.execute(
                f"SELECT id, diligence_hours FROM {table} WHERE email_date = %s",
                (email_date,)
            )
            existing = cur.fetchone()

            if existing:
                # 已有记录：勤奋时间更长则覆盖，否则跳过
                if d_hours <= (existing.get('diligence_hours') or 0):
                    logger.debug(f"跳过 {email_date}: 现有勤奋时间更长")
                    return None

                # 覆盖更新
                cur.execute(f"""
                    UPDATE {table}
                    SET subject = %s, sender = %s, content = %s, raw_content = %s,
                        diligence_start = %s, diligence_end = %s, diligence_hours = %s,
                        message_id = %s, source_filename = %s
                    WHERE id = %s
                """, (
                    subject, sender, content, raw_content,
                    d_start, d_end, d_hours,
                    message_id, source_filename,
                    existing['id']
                ))
                logger.info(f"更新 {email_date}: 勤奋时间更长，已覆盖")
                return existing['id']
            else:
                # 新记录
                cur.execute(f"""
                    INSERT INTO {table}
                        (email_date, subject, sender, content, raw_content,
                         diligence_start, diligence_end, diligence_hours,
                         message_id, source_filename)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    email_date, subject, sender, content, raw_content,
                    d_start, d_end, d_hours,
                    message_id, source_filename,
                ))
                new_id = cur.lastrowid
                logger.info(f"新增邮件: {email_date}, id={new_id}")
                return new_id
    except Exception as e:
        logger.error(f"保存邮件失败 ({email_date}): {e}")
        raise
    finally:
        conn.close()


def bulk_save_emails(email_data_list) -> dict:
    """
    批量保存邮件（逐条调用 save_email）

    Args:
        email_data_list: EmailData 对象列表（来自 email_parser.py）

    Returns:
        {'saved': int, 'skipped': int, 'failed': int}
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
                message_id='',  # EmailData 中暂无此字段
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
    查询指定月份的所有邮件

    Args:
        year: 年份
        month: 月份 (1-12)

    Returns:
        邮件字典列表
    """
    ensure_year_table(year)
    table = get_table_name(year)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE MONTH(email_date) = %s ORDER BY email_date",
                (month,)
            )
            rows = cur.fetchall()
            # 将 date/time/decimal 转为可序列化类型
            return [_serialize_row(r) for r in rows]
    finally:
        conn.close()


def get_emails_by_date_range(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    按日期范围查询邮件（可能跨年）

    Args:
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        邮件字典列表
    """
    results = []
    for year in range(start_date.year, end_date.year + 1):
        ensure_year_table(year)
        table = get_table_name(year)
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE email_date BETWEEN %s AND %s ORDER BY email_date",
                    (start_date, end_date)
                )
                rows = cur.fetchall()
                results.extend([_serialize_row(r) for r in rows])
        finally:
            conn.close()

    return results


def get_email_by_date(email_date: date) -> Optional[Dict[str, Any]]:
    """
    查询单日邮件

    Args:
        email_date: 日期

    Returns:
        邮件字典或 None
    """
    year = email_date.year
    ensure_year_table(year)
    table = get_table_name(year)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE email_date = %s",
                (email_date,)
            )
            row = cur.fetchone()
            return _serialize_row(row) if row else None
    finally:
        conn.close()


def get_diligence_stats(year: int) -> Dict[str, Any]:
    """
    获取指定年份的勤奋时间统计

    Args:
        year: 年份

    Returns:
        {
            'year': int,
            'months': [{'month': int, 'hours': float, 'entries': int, 'target': float, 'delta': float}],
            'total_hours': float,
            'total_target': float,
            'total_delta': float,
        }
    """
    import os
    target_hours = float(os.environ.get("DILIGENCE_TARGET_HOURS", "36"))

    ensure_year_table(year)
    table = get_table_name(year)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT MONTH(email_date) AS m,
                       COALESCE(SUM(diligence_hours), 0) AS total_hours,
                       COUNT(*) AS entries
                FROM {table}
                WHERE diligence_hours > 0
                GROUP BY MONTH(email_date)
                ORDER BY m
            """)
            rows = cur.fetchall()

        months = []
        total_hours = 0.0
        total_target = 0.0
        for row in rows:
            m = int(row['m'])
            hours = float(row['total_hours'])
            entries = int(row['entries'])
            months.append({
                'month': m,
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
    获取数据库中存在邮件数据的所有年份

    Returns:
        年份列表，从小到大排列
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 查询所有 email_ 开头的表
            cur.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME LIKE 'email\\_%'
                  AND TABLE_NAME != 'email_meta'
                ORDER BY TABLE_NAME
            """)
            rows = cur.fetchall()

        years = []
        for row in rows:
            table_name = row['TABLE_NAME']
            try:
                year = int(table_name.replace('email_', ''))
                # 检查表是否有数据
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
                        cnt = cur2.fetchone()['cnt']
                        if cnt > 0:
                            years.append(year)
            except (ValueError, Exception):
                continue

        return sorted(years)
    finally:
        conn.close()


def email_exists_by_date(email_date: date) -> bool:
    """
    检查指定日期是否已有邮件

    Args:
        email_date: 日期

    Returns:
        是否存在
    """
    return get_email_by_date(email_date) is not None


# ==================== 元数据操作 ====================

def save_meta(key: str, value: str):
    """
    保存元数据（UPSERT）

    Args:
        key: 键
        value: 值
    """
    ensure_meta_table()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_meta (meta_key, meta_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value)
            """, (key, value))
        logger.debug(f"元数据已保存: {key}")
    finally:
        conn.close()


def get_meta(key: str) -> Optional[str]:
    """
    获取元数据

    Args:
        key: 键

    Returns:
        值，不存在返回 None
    """
    ensure_meta_table()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT meta_value FROM email_meta WHERE meta_key = %s",
                (key,)
            )
            row = cur.fetchone()
            return row['meta_value'] if row else None
    finally:
        conn.close()


def delete_meta(key: str):
    """删除元数据"""
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
    将数据库行中的特殊类型转为可 JSON 序列化的类型

    Args:
        row: 数据库查询返回的字典

    Returns:
        序列化后的字典
    """
    if not row:
        return row

    import decimal
    from datetime import date as date_type, datetime as dt_type, timedelta

    result = {}
    for k, v in row.items():
        if isinstance(v, (date_type, dt_type)):
            result[k] = v.isoformat()
        elif isinstance(v, timedelta):
            # TIME 列返回的是 timedelta
            total_seconds = int(v.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            result[k] = f"{hours:02d}:{minutes:02d}"
        elif isinstance(v, decimal.Decimal):
            result[k] = float(v)
        else:
            result[k] = v

    return result
