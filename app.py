"""
CETWorkOverTime Web 服务
基于 Flask 提供 Web API 和前端页面，用于邮件抓取、处理和报告查看。
"""

import os
import sys
import logging
import threading
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for
try:
    import pyotp
except ImportError:
    pyotp = None

import config
from email_fetcher import EmailFetcher
from email_processor import EmailProcessor

# Markdown 渲染
try:
    import markdown
except ImportError:
    markdown = None

# 数据库模块（延迟初始化）
_db_available = False
_db_error_code = None
_db_error_message = ""
_db_import_error = None
try:
    from db import DatabaseDependencyError, init_db
    import email_repository
    _db_available = True
except ImportError as exc:
    DatabaseDependencyError = None
    _db_import_error = exc

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

@app.before_request
def check_login():
    # 白名单路由：登录页、登录API、静态文件
    allowed_routes = ['login_page', 'api_login', 'static']
    if request.endpoint not in allowed_routes:
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'ok': False, 'error': '未授权，请先登录'}), 401
            return redirect(url_for('login_page'))

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('email_processor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def _set_db_unavailable(reason_code: str, message: str):
    """记录数据库不可用原因，供日志和 API 统一复用。"""
    global _db_available, _db_error_code, _db_error_message
    _db_available = False
    _db_error_code = reason_code
    _db_error_message = message


def _database_unavailable_payload() -> dict:
    message = _db_error_message or "数据库不可用"
    reason_code = _db_error_code or "init_failed"
    return {
        "ok": False,
        "error": message,
        "reason_code": reason_code,
    }


def _database_unavailable_response():
    return jsonify(_database_unavailable_payload()), 503


def _database_status_unavailable_payload() -> dict:
    message = _db_error_message or "数据库不可用"
    reason_code = _db_error_code or "init_failed"
    return {
        "ok": True,
        "db_available": False,
        "reason_code": reason_code,
        "message": message,
    }


if _db_import_error is not None:
    _set_db_unavailable("init_failed", f"数据库模块加载失败: {_db_import_error}")

# 全局任务状态锁 & 状态
_task_lock = threading.Lock()
_task_status = {
    "running": False,
    "type": None,       # "fetch" | "process" | "scheduled"
    "message": "",
    "started_at": None,
    "finished_at": None
}

# ==================== 定时调度 ====================
SCHEDULE_INTERVAL = int(os.environ.get("SCHEDULE_INTERVAL_HOURS", "24")) * 3600  # 默认 24h
_scheduler_timer = None
_scheduler_info = {
    "enabled": True,
    "interval_hours": int(os.environ.get("SCHEDULE_INTERVAL_HOURS", "24")),
    "next_run": None,
    "last_run": None,
    "last_result": None
}


def _sync_eml_to_db_and_cleanup(status_prefix: str = ""):
    """
    扫描本地 .eml 文件，解析并入库，入库成功后按配置清理文件

    Args:
        status_prefix: 状态消息前缀（用于区分定时/手动）

    Returns:
        (synced, cleaned) 同步数量和清理数量
    """
    if not _db_available:
        logger.warning("数据库不可用，跳过入库")
        return 0, 0

    _update_status(True, _task_status.get("type"), f"{status_prefix}正在解析邮件并入库...")

    processor = EmailProcessor(config.WORK_SUMMARY_DIR)
    stats = processor.sync_to_db()
    synced = stats.get('saved', 0)

    cleaned = 0
    if config.CLEANUP_EML_AFTER_SYNC:
        _update_status(True, _task_status.get("type"), f"{status_prefix}正在清理本地 .eml 文件...")
        eml_dir = config.WORK_SUMMARY_DIR
        if eml_dir.exists():
            for eml_file in list(eml_dir.glob(f"*{config.EMAIL_FILE_EXTENSION}")):
                try:
                    eml_file.unlink()
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"清理文件失败: {eml_file.name}: {e}")
        logger.info(f"已清理 {cleaned} 个本地 .eml 文件")

    return synced, cleaned


def _scheduled_fetch_and_process():
    """定时任务：抓取邮件并入库"""
    _scheduler_info["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("⏰ 定时任务开始：自动抓取邮件并入库")

    with _task_lock:
        try:
            _update_status(True, "scheduled", "定时任务：正在连接邮箱...")

            if not config.IMAP_USERNAME or not config.IMAP_PASSWORD:
                _update_status(False, "scheduled", "定时任务跳过：未配置邮箱")
                _scheduler_info["last_result"] = "跳过（未配置邮箱）"
                return

            # 1) 抓取邮件
            fetcher = EmailFetcher(save_dir=config.WORK_SUMMARY_DIR)
            downloaded = 0
            if fetcher.connect():
                try:
                    _update_status(True, "scheduled", "定时任务：正在抓取邮件...")
                    downloaded = fetcher.fetch_emails(days=config.IMAP_SEARCH_DAYS)
                finally:
                    fetcher.disconnect()
            else:
                _update_status(False, "scheduled", "定时任务：连接邮箱失败")
                _scheduler_info["last_result"] = "失败（连接邮箱失败）"
                return

            # 2) 入库并清理
            synced, cleaned = _sync_eml_to_db_and_cleanup("定时任务：")

            result_msg = f"完成！下载 {downloaded} 封，入库 {synced} 封，清理 {cleaned} 个文件"
            _update_status(False, "scheduled", f"定时任务：{result_msg}")
            _scheduler_info["last_result"] = result_msg
            logger.info(f"⏰ 定时任务完成：{result_msg}")

        except Exception as e:
            logger.error(f"定时任务失败: {e}", exc_info=True)
            _update_status(False, "scheduled", f"定时任务失败: {e}")
            _scheduler_info["last_result"] = f"失败: {e}"

    # 调度下一次
    _schedule_next()


def _schedule_next():
    """调度下一次定时任务"""
    global _scheduler_timer
    if not _scheduler_info["enabled"]:
        return

    _scheduler_timer = threading.Timer(SCHEDULE_INTERVAL, _scheduled_fetch_and_process)
    _scheduler_timer.daemon = True
    _scheduler_timer.start()

    from datetime import timedelta
    next_run = datetime.now() + timedelta(seconds=SCHEDULE_INTERVAL)
    _scheduler_info["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"⏰ 下次定时抓取时间: {_scheduler_info['next_run']}")


def start_scheduler():
    """启动定时调度器"""
    if _scheduler_info["enabled"]:
        logger.info(f"⏰ 自动抓取调度已启动，间隔: {_scheduler_info['interval_hours']} 小时")
        _schedule_next()


def stop_scheduler():
    """停止定时调度器"""
    global _scheduler_timer
    if _scheduler_timer:
        _scheduler_timer.cancel()
        _scheduler_timer = None
    _scheduler_info["enabled"] = False


def _update_status(running: bool, task_type: str = None, message: str = ""):
    """更新全局任务状态"""
    _task_status["running"] = running
    _task_status["type"] = task_type
    _task_status["message"] = message
    if running:
        _task_status["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _task_status["finished_at"] = None
    else:
        _task_status["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """前端首页 - 勤奋时间仪表板"""
    return render_template("dashboard.html")


@app.route("/reports")
def reports_page():
    """报告管理页面"""
    return render_template("index.html")


@app.route("/login")
def login_page():
    """登录页面"""
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    """登录 API"""
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    
    if pyotp is None:
        return jsonify({"ok": False, "error": "服务端未安装 pyotp 依赖，无法校验动态验证码"}), 500

    totp = pyotp.TOTP(config.TOTP_SECRET)
    if totp.verify(password):
        session['logged_in'] = True
        return jsonify({"ok": True, "message": "登录成功"})
    return jsonify({"ok": False, "error": "动态验证码错误或已失效"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """登出 API"""
    session.pop('logged_in', None)
    return jsonify({"ok": True})


# ==================== API 路由 ====================

DILIGENCE_TARGET_HOURS = float(os.environ.get("DILIGENCE_TARGET_HOURS", "36"))


@app.route("/api/diligence")
def api_diligence():
    """获取勤奋时间统计数据，按年/月组织（优先从数据库）"""
    # 优先从数据库读取
    if _db_available:
        try:
            years = email_repository.get_all_years()
            if years:
                years_data = {}
                for year in years:
                    stats = email_repository.get_diligence_stats(year)
                    if stats['months']:
                        years_data[str(year)] = stats
                if years_data:
                    return jsonify({
                        "ok": True,
                        "source": "database",
                        "target_hours": DILIGENCE_TARGET_HOURS,
                        "years": years_data
                    })
        except Exception as e:
            logger.warning(f"从数据库读取勤奋时间失败，回退到文件: {e}")

    # 回退到文件系统读取
    import re as _re

    report_dir = config.OUTPUT_DIR
    monthly_data = {}

    if report_dir.exists():
        for report_file in report_dir.glob("*工作总结.md"):
            match = _re.search(r'(\d{4})年(\d{2})月', report_file.name)
            if not match:
                continue

            year = match.group(1)
            month = match.group(2)

            try:
                content = report_file.read_text(encoding="utf-8")
                pattern = r'\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]'
                matches = _re.findall(pattern, content)

                total_hours = 0.0
                for start_str, end_str in matches:
                    sh, sm = map(int, start_str.split(':'))
                    eh, em = map(int, end_str.split(':'))
                    start_min = sh * 60 + sm
                    end_min = eh * 60 + em
                    if end_min < start_min:
                        end_min += 24 * 60
                    total_hours += (end_min - start_min) / 60.0

                key = f"{year}-{month}"
                monthly_data[key] = {
                    "year": int(year),
                    "month": int(month),
                    "hours": round(total_hours, 2),
                    "target": DILIGENCE_TARGET_HOURS,
                    "delta": round(total_hours - DILIGENCE_TARGET_HOURS, 2),
                    "entries": len(matches)
                }
            except Exception as e:
                logger.warning(f"解析勤奋时间失败: {report_file.name}, {e}")

    # 按年分组
    years_data = {}
    for key in sorted(monthly_data.keys()):
        item = monthly_data[key]
        year_str = str(item["year"])
        if year_str not in years_data:
            years_data[year_str] = {
                "year": item["year"],
                "months": [],
                "total_hours": 0,
                "total_target": 0
            }
        years_data[year_str]["months"].append(item)
        years_data[year_str]["total_hours"] += item["hours"]
        years_data[year_str]["total_target"] += item["target"]

    # 计算年度汇总
    for yd in years_data.values():
        yd["total_hours"] = round(yd["total_hours"], 2)
        yd["total_delta"] = round(yd["total_hours"] - yd["total_target"], 2)

    return jsonify({
        "ok": True,
        "source": "file",
        "target_hours": DILIGENCE_TARGET_HOURS,
        "years": years_data
    })


@app.route("/api/diligence/<int:year>/<int:month>")
def api_month_diligence(year: int, month: int):
    """获取指定年月的每一天勤奋详情"""
    if not _db_available:
        return _database_unavailable_response()

    try:
        emails = email_repository.get_emails_by_month(year, month)
        days = []
        for em in emails:
            from datetime import date as date_type
            email_date = em.get('email_date')
            if isinstance(email_date, str):
                d_str = email_date
            else:
                d_str = email_date.strftime("%Y-%m-%d") if email_date else ""

            days.append({
                "date": d_str,
                "subject": em.get('subject', ''),
                "hours": em.get('diligence_hours', 0.0),
                "start": em.get('diligence_start', ''),
                "end": em.get('diligence_end', ''),
                "content": em.get('content', '')
            })
        
        # 按日期排序
        days.sort(key=lambda x: x['date'])

        return jsonify({
            "ok": True,
            "year": year,
            "month": month,
            "days": days
        })
    except Exception as e:
        logger.error(f"获取 {year}年{month}月 详情失败: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/status")
def api_status():
    """获取服务状态"""
    # 统计报告数量
    report_dir = config.OUTPUT_DIR
    report_count = len(list(report_dir.glob("*工作总结.md"))) if report_dir.exists() else 0

    # 统计邮件文件数量
    email_dir = config.WORK_SUMMARY_DIR
    email_count = len(list(email_dir.glob("*.eml"))) if email_dir.exists() else 0

    return jsonify({
        "ok": True,
        "task": _task_status,
        "stats": {
            "email_count": email_count,
            "report_count": report_count,
            "email_dir": str(email_dir),
            "output_dir": str(report_dir),
            "imap_configured": bool(config.IMAP_USERNAME and config.IMAP_PASSWORD)
        },
        "scheduler": _scheduler_info
    })


@app.route("/api/reports")
def api_reports():
    """获取所有报告列表（从数据库动态生成）"""
    reports = []

    if _db_available:
        try:
            years = email_repository.get_all_years()
            for year in sorted(years, reverse=True):
                stats = email_repository.get_diligence_stats(year)
                for month_info in sorted(stats.get('months', []), key=lambda m: m['month'], reverse=True):
                    month = month_info['month']
                    filename = config.REPORT_FILENAME_FORMAT.format(year=year, month=month)
                    reports.append({
                        "filename": filename,
                        "entries": month_info['entries'],
                        "hours": month_info['hours'],
                        "source": "database"
                    })
        except Exception as e:
            logger.warning(f"从数据库获取报告列表失败: {e}")

    # 如果数据库无数据，回退到本地文件
    if not reports:
        report_dir = config.OUTPUT_DIR
        if report_dir.exists():
            for f in sorted(report_dir.glob("*工作总结.md"), reverse=True):
                stat = f.stat()
                reports.append({
                    "filename": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "file"
                })

    return jsonify({"ok": True, "reports": reports})


def _generate_report_from_db(year: int, month: int) -> str:
    """从数据库动态生成指定月份的 Markdown 报告"""
    emails = email_repository.get_emails_by_month(year, month)
    if not emails:
        return f"# {year}年{month:02d}月工作总结\n\n暂无数据。"

    lines = []
    lines.append(f"# {year}年{month:02d}月工作总结")
    lines.append("")
    lines.append("## 📊 统计信息")
    lines.append("")
    lines.append(f"- **工作日数**: {len(emails)} 天")

    total_hours = sum(e.get('diligence_hours', 0) for e in emails)
    lines.append(f"- **勤奋时间合计**: {total_hours:.2f} 小时")
    lines.append("")
    lines.append("## 📝 工作日志")
    lines.append("")

    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    for em in emails:
        from datetime import date as date_type
        email_date = em.get('email_date', '')
        if isinstance(email_date, str):
            parts = email_date.split('-')
            d = date_type(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            d = email_date

        date_str = f"{d.year}年{d.month:02d}月{d.day:02d}日"
        wd = weekdays[d.weekday()]
        lines.append(f"### {date_str} ({wd})")
        lines.append("")

        if em.get('subject'):
            lines.append(f"**主题**: {em['subject']}")

        d_start = em.get('diligence_start', '')
        d_end = em.get('diligence_end', '')
        d_hours = em.get('diligence_hours', 0)
        if d_hours and d_hours > 0:
            lines.append(f"**勤奋时间**: {d_start} ~ {d_end}（{d_hours:.2f} 小时）")
        lines.append("")

        content = em.get('content', '')
        if content:
            lines.append("**工作内容**:")
            lines.append("")
            for line in content.split('\n'):
                line = line.strip()
                if line:
                    if line[0].isdigit() or line.startswith('•') or line.startswith('-'):
                        lines.append(f"- {line}")
                    else:
                        lines.append(line)
                else:
                    lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("*此报告从数据库动态生成*")
    return '\n'.join(lines)


@app.route("/api/report/<path:filename>")
def api_report(filename):
    """获取单个报告内容（优先从数据库动态生成）"""
    import re as _re

    raw_md = None

    # 尝试从文件名解析年月，从数据库生成
    if _db_available:
        match = _re.search(r'(\d{4})年(\d{2})月', filename)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            try:
                raw_md = _generate_report_from_db(year, month)
            except Exception as e:
                logger.warning(f"从数据库生成报告失败，尝试本地文件: {e}")

    # 回退到本地文件
    if raw_md is None:
        report_path = config.OUTPUT_DIR / filename
        if not report_path.exists() or not report_path.is_file():
            abort(404, description=f"报告不存在: {filename}")
        try:
            report_path.resolve().relative_to(config.OUTPUT_DIR.resolve())
        except ValueError:
            abort(403, description="非法路径")
        raw_md = report_path.read_text(encoding="utf-8")

    # 是否请求 HTML 渲染
    render_html = request.args.get("html", "1") == "1"
    if render_html and markdown:
        html_content = markdown.markdown(
            raw_md,
            extensions=["tables", "fenced_code", "nl2br", "sane_lists"]
        )
        return jsonify({"ok": True, "filename": filename, "html": html_content, "markdown": raw_md})
    else:
        return jsonify({"ok": True, "filename": filename, "markdown": raw_md})


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    """触发邮件抓取（抓取 → 入库 → 清理）"""
    if _task_status["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行中，请稍后重试"}), 409

    data = request.get_json(silent=True) or {}
    days = data.get("days", config.IMAP_SEARCH_DAYS)
    force = data.get("force", False)

    if not config.IMAP_USERNAME or not config.IMAP_PASSWORD:
        return jsonify({"ok": False, "error": "未配置邮箱账号，请设置环境变量 EMAIL_USERNAME 和 EMAIL_PASSWORD"}), 400

    def _do_fetch():
        with _task_lock:
            try:
                _update_status(True, "fetch", "正在连接邮箱...")
                fetcher = EmailFetcher(save_dir=config.WORK_SUMMARY_DIR)
                downloaded = 0
                if fetcher.connect():
                    try:
                        action_text = "正在强制全量重抓全部邮件..." if force else f"正在抓取最近 {days} 天的邮件..."
                        _update_status(True, "fetch", action_text)
                        downloaded = fetcher.fetch_emails(days=days, force=force)
                    finally:
                        fetcher.disconnect()
                else:
                    _update_status(False, "fetch", "连接邮箱失败，请检查配置")
                    return

                # 入库并清理
                synced, cleaned = _sync_eml_to_db_and_cleanup()
                _update_status(False, "fetch", f"完成！下载 {downloaded} 封，入库 {synced} 封，清理 {cleaned} 个文件")
            except Exception as e:
                logger.error(f"邮件抓取失败: {e}", exc_info=True)
                _update_status(False, "fetch", f"抓取失败: {e}")

    thread = threading.Thread(target=_do_fetch, daemon=True)
    thread.start()

    message = "邮件全量重抓任务已启动" if force else "邮件抓取任务已启动"
    return jsonify({"ok": True, "message": message})


@app.route("/api/process", methods=["POST"])
def api_process():
    """触发邮件处理生成报告"""
    if _task_status["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行中，请稍后重试"}), 409

    data = request.get_json(silent=True) or {}
    force = data.get("force", False)
    months = data.get("months", None)  # None = 全部月份

    def _do_process():
        with _task_lock:
            try:
                _update_status(True, "process", "正在处理邮件...")

                processor = EmailProcessor(config.WORK_SUMMARY_DIR)
                incremental = not force

                if force:
                    cache_path = config.OUTPUT_DIR / config.CACHE_FILENAME
                    if cache_path.exists():
                        cache_path.unlink()

                # 解析月份参数
                selected_months = None
                if months:
                    stats = processor.get_statistics()
                    monthly_stats = stats.get("monthly_stats", {})
                    if months == "all":
                        selected_months = sorted(monthly_stats.keys())
                    else:
                        month_list = [m.strip() for m in months.split(",")]
                        selected_months = [m for m in month_list if m in monthly_stats]

                success = processor.process_emails_for_months(selected_months, incremental=incremental)

                if success:
                    _update_status(False, "process", "报告生成完成！")
                else:
                    _update_status(False, "process", "报告生成失败，请查看日志")
            except Exception as e:
                logger.error(f"处理邮件失败: {e}", exc_info=True)
                _update_status(False, "process", f"处理失败: {e}")

    thread = threading.Thread(target=_do_process, daemon=True)
    thread.start()

    return jsonify({"ok": True, "message": "报告生成任务已启动"})


@app.route("/api/fetch-and-process", methods=["POST"])
def api_fetch_and_process():
    """一键抓取邮件并入库（与定时任务行为一致）"""
    if _task_status["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行中，请稍后重试"}), 409

    if not config.IMAP_USERNAME or not config.IMAP_PASSWORD:
        return jsonify({"ok": False, "error": "未配置邮箱账号，请设置环境变量 EMAIL_USERNAME 和 EMAIL_PASSWORD"}), 400

    data = request.get_json(silent=True) or {}
    days = data.get("days", config.IMAP_SEARCH_DAYS)
    force = data.get("force", False)

    def _do_all():
        with _task_lock:
            try:
                # 1) 抓取邮件
                _update_status(True, "fetch-and-process", "正在连接邮箱...")
                fetcher = EmailFetcher(save_dir=config.WORK_SUMMARY_DIR)
                downloaded = 0
                if fetcher.connect():
                    try:
                        action_text = "正在强制全量重抓全部邮件..." if force else f"正在抓取最近 {days} 天的邮件..."
                        _update_status(True, "fetch-and-process", action_text)
                        downloaded = fetcher.fetch_emails(days=days, force=force)
                    finally:
                        fetcher.disconnect()
                else:
                    _update_status(False, "fetch-and-process", "连接邮箱失败，请检查配置")
                    return

                # 2) 入库并清理
                synced, cleaned = _sync_eml_to_db_and_cleanup()
                _update_status(False, "fetch-and-process", f"完成！下载 {downloaded} 封，入库 {synced} 封，清理 {cleaned} 个文件")
            except Exception as e:
                logger.error(f"一键抓取入库失败: {e}", exc_info=True)
                _update_status(False, "fetch-and-process", f"失败: {e}")

    thread = threading.Thread(target=_do_all, daemon=True)
    thread.start()

    message = "全量重抓并入库任务已启动" if force else "一键抓取并入库任务已启动"
    return jsonify({"ok": True, "message": message})


# ==================== 数据库查询 API ====================

@app.route("/api/emails")
def api_emails():
    """查询指定年月的邮件列表"""
    if not _db_available:
        return _database_unavailable_response()

    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)

    if not year:
        return jsonify({"ok": False, "error": "请指定 year 参数"}), 400

    try:
        if month:
            emails = email_repository.get_emails_by_month(year, month)
        else:
            from datetime import date
            emails = email_repository.get_emails_by_date_range(
                date(year, 1, 1), date(year, 12, 31)
            )
        return jsonify({"ok": True, "count": len(emails), "emails": emails})
    except Exception as e:
        logger.error(f"查询邮件失败: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/email/<date_str>")
def api_email_detail(date_str):
    """查询单日邮件详情"""
    if not _db_available:
        return _database_unavailable_response()

    try:
        from datetime import date
        parts = date_str.split('-')
        target_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        email_data = email_repository.get_email_by_date(target_date)
        if email_data:
            return jsonify({"ok": True, "email": email_data})
        else:
            return jsonify({"ok": False, "error": f"未找到 {date_str} 的邮件"}), 404
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": "日期格式错误，请使用 YYYY-MM-DD"}), 400
    except Exception as e:
        logger.error(f"查询邮件详情失败: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sync-db", methods=["POST"])
def api_sync_db():
    """触发历史数据同步入库"""
    if not _db_available:
        return _database_unavailable_response()

    if _task_status["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行中，请稍后重试"}), 409

    def _do_sync():
        with _task_lock:
            try:
                _update_status(True, "sync-db", "正在同步历史数据到数据库...")
                processor = EmailProcessor(config.WORK_SUMMARY_DIR)
                stats = processor.sync_to_db()
                msg = f"完成！新增 {stats.get('saved', 0)}, 跳过 {stats.get('skipped', 0)}, 失败 {stats.get('failed', 0)}"
                _update_status(False, "sync-db", msg)
            except Exception as e:
                logger.error(f"数据库同步失败: {e}", exc_info=True)
                _update_status(False, "sync-db", f"同步失败: {e}")

    thread = threading.Thread(target=_do_sync, daemon=True)
    thread.start()

    return jsonify({"ok": True, "message": "历史数据同步任务已启动"})


@app.route("/api/db-status")
def api_db_status():
    """获取数据库状态"""
    if not _db_available:
        return jsonify(_database_status_unavailable_payload())

    try:
        years = email_repository.get_all_years()
        year_counts = {}
        total = 0
        for year in years:
            from db import get_connection, get_table_name
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM {get_table_name(year)}")
                    cnt = cur.fetchone()['cnt']
                    year_counts[str(year)] = cnt
                    total += cnt
            finally:
                conn.close()

        return jsonify({
            "ok": True,
            "db_available": True,
            "host": config.DB_HOST,
            "database": config.DB_NAME,
            "years": year_counts,
            "total_records": total
        })
    except Exception as e:
        return jsonify({
            "ok": True,
            "db_available": False,
            "reason_code": "init_failed",
            "message": f"数据库初始化失败: {e}",
            "error": str(e),
        })


# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"ok": False, "error": str(e)}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"ok": False, "error": "服务器内部错误"}), 500


# gunicorn 启动时也会执行此处（模块顶层初始化）
# 使用 WERKZEUG_RUN_MAIN 避免 Flask debug 模式下 reloader 重复启动
_scheduler_started = False


def _ensure_scheduler():
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        start_scheduler()


# 首次导入时初始化数据库和调度器
_ensure_scheduler()
if _db_import_error is not None:
    logger.warning(f"⚠️ 数据库模块加载失败（服务仍可运行，但数据库功能不可用）: {_db_error_message}")
elif _db_available:
    try:
        init_db()
        _db_error_code = None
        _db_error_message = ""
        logger.info("✅ 数据库初始化成功")
    except DatabaseDependencyError as e:
        _set_db_unavailable("missing_driver", str(e))
        logger.warning(f"⚠️ 数据库驱动缺失（服务仍可运行，但数据库功能不可用）: {e}")
    except Exception as e:
        _set_db_unavailable("init_failed", f"数据库初始化失败: {e}")
        logger.warning(f"⚠️ 数据库初始化失败（服务仍可运行，但数据库功能不可用）: {e}")


if __name__ == "__main__":
    # 本地开发模式
    print("\n🌐 CETWorkOverTime Web 服务启动中...")
    print(f"   访问地址: http://localhost:5000")
    print(f"   自动抓取间隔: {_scheduler_info['interval_hours']} 小时")
    print("   按 Ctrl+C 停止\n")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
