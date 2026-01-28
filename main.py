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
  python main.py                          # 交互式选择月份（默认）
  python main.py --dir ./工作总结           # 指定邮件目录
  python main.py --output ./reports       # 指定输出目录
  python main.py --stats                  # 只显示统计信息
  python main.py --verbose                # 详细日志输出
  python main.py --months 2024-07,2024-08 # 指定生成特定月份
  python main.py --months all             # 生成所有月份
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
        help='指定要生成的月份，格式：2024-07,2024-08 或 all (默认: 交互式选择)'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='邮件工作总结汇总程序 v1.0'
    )

    return parser.parse_args()


def print_banner():
    """打印程序横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    邮件工作总结汇总程序                        ║
║                     Email Work Summary Tool                   ║
║                          Version 1.0                         ║
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

        # 验证目录
        if not work_dir.exists():
            print(f"❌ 错误: 邮件目录不存在: {work_dir}")
            sys.exit(1)

        # 创建输出目录
        output_dir.mkdir(parents=True, exist_ok=True)
        config.OUTPUT_DIR = output_dir

        print(f"📂 邮件目录: {work_dir}")
        print(f"📁 输出目录: {output_dir}")

        # 创建邮件处理器
        processor = EmailProcessor(work_dir)

        # 获取统计信息
        stats = processor.get_statistics()
        print_statistics(stats)

        # 如果只需要统计信息，则退出
        if args.stats:
            print("\n✅ 统计信息显示完成")
            return

        # 确认是否继续处理
        if stats.get('parsed_emails', 0) == 0:
            print("\n❌ 没有找到可处理的邮件文件")
            sys.exit(1)

        # 选择要生成的月份
        monthly_stats = stats.get('monthly_stats', {})
        selected_months = []

        if args.months:
            # 命令行参数指定
            selected_months = parse_months_argument(args.months, monthly_stats)
            if not selected_months:
                print("\n❌ 没有有效的月份选择")
                sys.exit(1)
        else:
            # 默认使用交互式选择
            selected_months = select_months_interactive(monthly_stats)
            if not selected_months:
                print("\n⚠️ 未选择任何月份，程序退出")
                return

        print(f"\n📋 将生成以下月份的报告:")
        for month in selected_months:
            count = monthly_stats.get(month, 0)
            print(f"   📅 {month} ({count} 封邮件)")

        print(f"\n🚀 开始处理 {stats.get('parsed_emails', 0)} 封邮件...")

        # 处理邮件并生成指定月份的报告
        success = processor.process_emails_for_months(selected_months)

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