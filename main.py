"""
邮件工作总结汇总程序
主程序入口

功能：
- 读取指定目录下的邮件文件(.eml格式)
- 提取邮件的时间、主题和正文内容
- 按月份组织邮件并按时间顺序排列
- 生成Markdown格式的工作总结报告

作者：AI Assistant
版本：1.0
"""

import sys
import logging
import argparse
from pathlib import Path

import config
from email_processor import EmailProcessor
from email_fetcher import EmailFetcher


def setup_logging(log_level: str = "INFO"):
    """
    设置日志配置

    Args:
        log_level: 日志级别
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=config.LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('email_processor.log', encoding='utf-8')
        ]
    )


def parse_arguments():
    """
    解析命令行参数

    Returns:
        解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description="邮件工作总结汇总程序",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                          # 默认增量处理所有月份
  python main.py --fetch                  # 从邮箱获取最近30天的邮件
  python main.py --fetch --days 7         # 从邮箱获取最近7天的邮件
  python main.py --fetch-and-process      # 获取邮件并自动处理生成报告
  python main.py --dir ./工作总结           # 指定邮件目录
  python main.py --output ./reports       # 指定输出目录
  python main.py --stats                  # 只显示统计信息
  python main.py --verbose                # 详细日志输出
  python main.py --months 2024-07,2024-08 # 指定处理特定月份
  python main.py -f                       # 强制全量重新处理
        """
    )

    parser.add_argument(
        '--dir', '-d',
        type=str,
        default=str(config.WORK_SUMMARY_DIR),
        help=f'邮件文件目录 (默认: {config.WORK_SUMMARY_DIR})'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=str(config.OUTPUT_DIR),
        help=f'输出目录 (默认: {config.OUTPUT_DIR})'
    )

    parser.add_argument(
        '--stats', '-s',
        action='store_true',
        help='只显示统计信息，不生成报告'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细日志输出'
    )

    parser.add_argument(
        '--months', '-m',
        type=str,
        help='指定要处理的月份，格式：2024-07,2024-08 (默认: 处理所有月份)'
    )

    parser.add_argument(
        '--fetch',
        action='store_true',
        help='仅从邮箱获取邮件，不进行处理'
    )

    parser.add_argument(
        '--no-fetch',
        action='store_true',
        help='跳过邮件获取，仅处理本地已有邮件'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=config.IMAP_SEARCH_DAYS,
        help=f'获取邮件时搜索最近多少天 (默认: {config.IMAP_SEARCH_DAYS})'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='邮件工作总结汇总程序 v1.2'
    )

    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制全量重抓/处理，忽略抓取与处理缓存'
    )

    return parser.parse_args()


def print_banner():
    """打印程序横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    邮件工作总结汇总程序                        ║
║                     Email Work Summary Tool                   ║
║                          Version 1.2                         ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_statistics(stats: dict):
    """
    打印统计信息

    Args:
        stats: 统计信息字典
    """
    print("\n" + "="*60)
    print("📊 邮件文件统计信息")
    print("="*60)
    print(f"📁 总文件数: {stats.get('total_files', 0)}")
    print(f"✅ 可解析邮件: {stats.get('parsed_emails', 0)}")

    date_range = stats.get('date_range', {})
    if date_range.get('start') and date_range.get('end'):
        print(f"📅 时间范围: {date_range['start'].strftime('%Y-%m-%d')} 至 {date_range['end'].strftime('%Y-%m-%d')}")

    monthly_stats = stats.get('monthly_stats', {})
    if monthly_stats:
        print(f"\n📈 月度分布:")
        for month, count in sorted(monthly_stats.items()):
            print(f"   {month}: {count} 封邮件")

    print("="*60)


def select_months_interactive(monthly_stats: dict) -> list:
    """
    交互式选择月份

    Args:
        monthly_stats: 月度统计信息

    Returns:
        选择的月份列表
    """
    if not monthly_stats:
        return []

    print("\n📅 可用月份列表:")
    months = sorted(monthly_stats.keys())
    for i, month in enumerate(months, 1):
        count = monthly_stats[month]
        print(f"   {i:2d}. {month} ({count} 封邮件)")

    print(f"\n选择选项:")
    print(f"   0. 生成所有月份")
    print(f"   输入月份编号（用逗号分隔，如：1,3,5）")

    while True:
        try:
            choice = input("\n请输入选择: ").strip()

            if choice == "0" or choice.lower() == "all":
                return months

            if not choice:
                continue

            # 解析选择的编号
            selected_indices = [int(x.strip()) - 1 for x in choice.split(',')]
            selected_months = []

            for idx in selected_indices:
                if 0 <= idx < len(months):
                    selected_months.append(months[idx])
                else:
                    print(f"❌ 无效的编号: {idx + 1}")
                    break
            else:
                if selected_months:
                    print(f"\n✅ 已选择月份: {', '.join(selected_months)}")
                    return selected_months

        except ValueError:
            print("❌ 输入格式错误，请输入数字编号")
        except KeyboardInterrupt:
            print("\n\n⚠️ 用户取消选择")
            return []


def parse_months_argument(months_arg: str, monthly_stats: dict) -> list:
    """
    解析月份参数

    Args:
        months_arg: 月份参数字符串
        monthly_stats: 月度统计信息

    Returns:
        解析后的月份列表
    """
    if not months_arg or months_arg.lower() == "all":
        return sorted(monthly_stats.keys())

    selected_months = []
    for month in months_arg.split(','):
        month = month.strip()
        if month in monthly_stats:
            selected_months.append(month)
        else:
            print(f"⚠️ 警告: 月份 {month} 不存在，已跳过")

    return selected_months


def main():
    """主函数"""
    try:
        # 解析命令行参数
        args = parse_arguments()

        # 设置日志
        log_level = "DEBUG" if args.verbose else config.LOG_LEVEL
        setup_logging(log_level)

        # 打印横幅
        print_banner()

        # 更新配置
        work_dir = Path(args.dir)
        output_dir = Path(args.output)

        # 确保邮件目录存在（自动创建）
        work_dir.mkdir(parents=True, exist_ok=True)

        # 创建输出目录
        output_dir.mkdir(parents=True, exist_ok=True)
        config.OUTPUT_DIR = output_dir

        print(f"📂 邮件目录: {work_dir}")
        print(f"📁 输出目录: {output_dir}")

        # ====== 邮件获取 ======
        # 默认先获取邮件，除非指定 --no-fetch 或未配置邮箱
        should_fetch = not args.no_fetch
        if should_fetch and config.IMAP_USERNAME and config.IMAP_PASSWORD:
            fetcher = EmailFetcher(save_dir=work_dir)
            if fetcher.connect():
                try:
                    downloaded = fetcher.fetch_emails(days=args.days, force=args.force)
                    if downloaded > 0:
                        print(f"\n📥 成功下载 {downloaded} 封新邮件")
                    else:
                        print(f"\n📭 没有新邮件需要下载")
                finally:
                    fetcher.disconnect()

                # --fetch 仅获取模式，到此结束
                if args.fetch:
                    print("\n🎉 邮件获取完成！")
                    sys.exit(0)

                print("\n" + "─" * 60)
                print("📝 开始处理邮件并生成报告...")
            else:
                if args.fetch:
                    sys.exit(1)
                print("\n⚠️ 邮件获取失败，将继续处理本地已有邮件...")
        elif args.fetch:
            print("❌ 未配置邮箱账号，无法获取邮件")
            print("   请在 .env 文件中设置 EMAIL_USERNAME 和 EMAIL_PASSWORD")
            sys.exit(1)

        # 创建邮件处理器
        processor = EmailProcessor(work_dir)

        # 确定处理模式（默认增量，--force 切换为全量）
        incremental = not args.force
        if args.force:
            cache_path = output_dir / config.CACHE_FILENAME
            if cache_path.exists():
                cache_path.unlink()
                print("🗑️ 已清除处理缓存，将全量重新处理")

        # --stats 或全量模式：需要完整统计信息
        if args.stats or not incremental:
            stats = processor.get_statistics()
            print_statistics(stats)

            if args.stats:
                print("\n✅ 统计信息显示完成")
                return

            if stats.get('parsed_emails', 0) == 0:
                print("\n❌ 没有找到可处理的邮件文件")
                sys.exit(1)

            monthly_stats = stats.get('monthly_stats', {})
            if args.months:
                selected_months = parse_months_argument(args.months, monthly_stats)
                if not selected_months:
                    print("\n❌ 没有有效的月份选择")
                    sys.exit(1)
            else:
                selected_months = sorted(monthly_stats.keys())

            print(f"\n📦 模式: 全量处理")
            print(f"📋 将处理 {len(selected_months)} 个月份的报告")
            print(f"\n🚀 开始处理 {stats.get('parsed_emails', 0)} 封邮件...")
        else:
            # 增量模式：跳过全量统计，直接处理
            print(f"\n🔄 模式: 增量处理")
            if args.months:
                # 需要简单扫描获取可用月份列表来验证
                stats = processor.get_statistics()
                monthly_stats = stats.get('monthly_stats', {})
                selected_months = parse_months_argument(args.months, monthly_stats)
                if not selected_months:
                    print("\n❌ 没有有效的月份选择")
                    sys.exit(1)
            else:
                # 默认：处理所有月份，传入 None 让处理器自行决定
                selected_months = None

        # 处理邮件并生成报告
        success = processor.process_emails_for_months(selected_months, incremental=incremental)

        if success:
            print("\n🎉 程序执行成功！")
            sys.exit(0)
        else:
            print("\n❌ 程序执行失败，请检查日志文件")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断程序执行")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序执行时发生未预期的错误: {e}")
        logging.error(f"主程序异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
