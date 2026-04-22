"""Manual entrypoint for recalculating derived diligence fields."""

from __future__ import annotations

import argparse
from datetime import date

from db import init_db
import email_repository


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="重算数据库中的勤奋时长派生字段（diligence_start / diligence_end / diligence_hours）"
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        help="起始日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        help="结束日期，格式 YYYY-MM-DD",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_arguments(argv)

    init_db()
    stats = email_repository.recalculate_diligence_fields(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print("已按 17:45 起算、0.5 小时档位向下取整规则重算勤奋时长。")
    print("注意：.process_cache.json 和 fetch_cache 不缓存仪表盘结果；如果只改了 content，需要执行这一步让派生字段同步。")
    print(
        f"共扫描 {stats['scanned']} 条记录，更新 {stats['updated']} 条记录。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
