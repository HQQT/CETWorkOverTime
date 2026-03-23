"""
历史数据迁移脚本

将本地 .eml 文件解析后批量写入 MySQL 数据库。
运行方式: python migrate_to_db.py
"""

import sys
import logging
from pathlib import Path

import config
from db import init_db
from email_processor import EmailProcessor

logging.basicConfig(
    level=logging.INFO,
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def main():
    print("=" * 60)
    print("📦 CETWorkOverTime 历史数据迁移工具")
    print("=" * 60)
    print(f"📂 邮件目录: {config.WORK_SUMMARY_DIR}")
    print(f"🗄️  目标数据库: {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    print()

    # 初始化数据库（自动建表）
    try:
        init_db()
        print("✅ 数据库连接正常，表结构已就绪")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print("   请检查 .env 中的数据库配置")
        sys.exit(1)

    # 执行迁移
    try:
        processor = EmailProcessor(config.WORK_SUMMARY_DIR)
        stats = processor.sync_to_db()

        print()
        print("=" * 60)
        print("📊 迁移结果")
        print("=" * 60)
        print(f"   ✅ 新增入库: {stats.get('saved', 0)} 封")
        print(f"   ⏭️  已存在跳过: {stats.get('skipped', 0)} 封")
        print(f"   ❌ 失败: {stats.get('failed', 0)} 封")
        print()
        print("🎉 迁移完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        logger.error(f"迁移失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
