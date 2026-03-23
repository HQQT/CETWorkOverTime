"""
邮件获取模块 - 通过 IMAP 协议从邮箱自动下载邮件

支持 Foxmail/QQ 邮箱，使用 IMAP over SSL 连接。
"""

import imaplib
import email
import json
import logging
import re
import os
import ssl
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import List, Optional, Set, Tuple

import config

logger = logging.getLogger(__name__)


class EmailFetcher:
    """邮件获取器 - 通过 IMAP 从邮箱下载邮件"""

    def __init__(self, save_dir: Optional[Path] = None):
        """
        初始化邮件获取器

        Args:
            save_dir: 邮件保存目录，默认使用配置中的工作总结目录
        """
        self.save_dir = save_dir or config.WORK_SUMMARY_DIR
        self.connection: Optional[imaplib.IMAP4_SSL] = None
        self.fetch_cache_path = config.OUTPUT_DIR / '.fetch_cache.json'

        # 确保保存目录存在
        self.save_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"邮件获取器初始化完成，保存目录: {self.save_dir}")

    def connect(self) -> bool:
        """
        连接到 IMAP 服务器并登录

        Returns:
            是否连接成功
        """
        try:
            username = config.IMAP_USERNAME
            password = config.IMAP_PASSWORD

            if not username or not password:
                print("❌ 错误: 未配置邮箱账号或授权码")
                print("   请在 .env 文件中设置 EMAIL_USERNAME 和 EMAIL_PASSWORD")
                print("   或设置对应的环境变量")
                return False

            print(f"📧 正在连接邮箱服务器 {config.IMAP_SERVER}:{config.IMAP_PORT} ...")
            logger.info(f"连接 IMAP 服务器: {config.IMAP_SERVER}:{config.IMAP_PORT}")

            if config.IMAP_USE_SSL:
                context = ssl.create_default_context()
                self.connection = imaplib.IMAP4_SSL(
                    config.IMAP_SERVER,
                    config.IMAP_PORT,
                    ssl_context=context
                )
            else:
                self.connection = imaplib.IMAP4(
                    config.IMAP_SERVER,
                    config.IMAP_PORT
                )

            # 登录
            self.connection.login(username, password)
            print(f"✅ 登录成功: {username}")
            logger.info(f"IMAP 登录成功: {username}")
            return True

        except imaplib.IMAP4.error as e:
            print(f"❌ 邮箱登录失败: {e}")
            print("   请检查邮箱地址和 IMAP 授权码是否正确")
            logger.error(f"IMAP 登录失败: {e}")
            return False
        except Exception as e:
            print(f"❌ 连接邮箱服务器失败: {e}")
            logger.error(f"IMAP 连接失败: {e}")
            return False

    def disconnect(self):
        """断开 IMAP 连接"""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            try:
                self.connection.logout()
            except Exception:
                pass
            self.connection = None
            logger.info("IMAP 连接已断开")

    def _load_fetch_cache(self) -> dict:
        """加载获取缓存（优先从数据库，回退到 JSON 文件）"""
        # 尝试从数据库读取
        try:
            import email_repository
            import json as _json
            cache_value = email_repository.get_meta('fetch_cache')
            if cache_value:
                cache = _json.loads(cache_value)
                logger.debug(f"从数据库加载获取缓存: last_uid={cache.get('last_uid')}")
                return cache
        except Exception as e:
            logger.debug(f"数据库缓存读取失败，回退到文件: {e}")

        # 回退到 JSON 文件
        try:
            if self.fetch_cache_path.exists():
                with open(self.fetch_cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"加载获取缓存失败: {e}")
        return {}

    def _save_fetch_cache(self, uidvalidity: str, max_uid: int):
        """保存 UIDVALIDITY 和最大 UID（同时写数据库和 JSON 文件）"""
        cache = {
            'uidvalidity': uidvalidity,
            'last_uid': max_uid,
            'last_fetch_date': datetime.now().strftime('%Y-%m-%d')
        }

        # 写入数据库
        try:
            import email_repository
            import json as _json
            email_repository.save_meta('fetch_cache', _json.dumps(cache))
            logger.info(f"获取缓存已保存到数据库: last_uid={max_uid}")
        except Exception as e:
            logger.debug(f"保存缓存到数据库失败: {e}")

        # 同时写 JSON 文件（兼容旧流程）
        try:
            config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.fetch_cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
        except Exception as e:
            logger.debug(f"保存获取缓存到文件失败: {e}")

    def clear_fetch_cache(self):
        """清理抓取缓存（数据库 + 本地 JSON）。"""
        try:
            import email_repository
            email_repository.delete_meta('fetch_cache')
            logger.info("已清理数据库中的抓取缓存")
        except Exception as e:
            logger.debug(f"清理数据库抓取缓存失败: {e}")

        try:
            if self.fetch_cache_path.exists():
                self.fetch_cache_path.unlink()
                logger.info(f"已删除抓取缓存文件: {self.fetch_cache_path}")
        except Exception as e:
            logger.debug(f"删除抓取缓存文件失败: {e}")

    def fetch_emails(self, days: int = 365, force: bool = False) -> int:
        """
        搜索并下载邮件（UID 增量）

        首次运行搜索全部，之后只搜索新增的 UID。

        Args:
            days: 首次搜索最近多少天（仅首次生效）
            force: 是否忽略抓取缓存并强制全量重抓

        Returns:
            新下载的邮件数量
        """
        if not self.connection:
            print("❌ 未连接到邮箱服务器")
            return 0

        try:
            # 选择邮箱文件夹
            mailbox = config.IMAP_MAILBOX
            status, select_data = self.connection.select(mailbox, readonly=True)
            if status != 'OK':
                print(f"❌ 无法打开邮箱文件夹: {mailbox}")
                return 0

            print(f"📂 已打开邮箱文件夹: {mailbox}")

            # 获取 UIDVALIDITY（邮箱文件夹有效性标记）
            status, uidval_data = self.connection.response('UIDVALIDITY')
            uidvalidity = uidval_data[0].decode() if uidval_data and uidval_data[0] else ''

            # 加载缓存，判断是否增量模式
            cache = {}
            is_incremental = False
            if force:
                self.clear_fetch_cache()
                logger.info("强制全量模式: 忽略抓取缓存并重新扫描全部邮件")
                print("🔄 强制全量模式，重新扫描全部邮件...")
            else:
                cache = self._load_fetch_cache()
                is_incremental = (
                    cache.get('last_uid') and
                    cache.get('uidvalidity') == uidvalidity
                )

            if is_incremental:
                last_uid = cache['last_uid']
                # 搜索 UID 大于上次记录的新邮件
                search_criteria = f'UID {last_uid + 1}:*'
                logger.info(f"增量模式: 搜索 UID > {last_uid}")
                print(f"🔍 增量模式，搜索新邮件 (UID > {last_uid}) ...")

                status, data = self.connection.uid('search', None, 'ALL')
                if status != 'OK':
                    return 0

                all_uids = data[0].split() if data[0] else []
                # 只保留比 last_uid 大的
                new_uids = [u for u in all_uids if int(u) > last_uid]

                if not new_uids:
                    print("📭 没有新邮件")
                    # 更新缓存中的最大 UID
                    max_uid = max(int(u) for u in all_uids) if all_uids else last_uid
                    self._save_fetch_cache(uidvalidity, max_uid)
                    return 0

                print(f"   📬 发现 {len(new_uids)} 封新邮件")
            else:
                # 首次运行：搜索全部邮件
                if not force and cache.get('uidvalidity') and cache.get('uidvalidity') != uidvalidity:
                    print("⚠️ 邮箱文件夹 UIDVALIDITY 已变更，重新全量搜索")

                if not force:
                    print(f"🔍 首次运行，搜索全部邮件...")
                status, data = self.connection.uid('search', None, 'ALL')
                if status != 'OK':
                    return 0

                new_uids = data[0].split() if data[0] else []
                if not new_uids:
                    print("📭 邮箱为空")
                    return 0

                print(f"   📬 共 {len(new_uids)} 封邮件")

            # 批量获取头部，过滤主题和去重
            existing_message_ids = self._get_existing_message_ids()
            logger.info(f"本地已有 {len(existing_message_ids)} 封邮件的 Message-ID")

            uids_to_download = self._batch_filter(new_uids, existing_message_ids)

            # 计算最大 UID 用于保存缓存
            all_status, all_data = self.connection.uid('search', None, 'ALL')
            all_uids_list = all_data[0].split() if all_data[0] else []
            max_uid = max(int(u) for u in all_uids_list) if all_uids_list else 0

            if not uids_to_download:
                print("📭 没有新邮件需要下载")
                self._save_fetch_cache(uidvalidity, max_uid)
                return 0

            print(f"📥 需要下载 {len(uids_to_download)} 封新邮件")

            # 下载新邮件
            downloaded = 0
            skipped = 0

            for i, uid in enumerate(uids_to_download, 1):
                try:
                    result = self._download_email(uid, existing_message_ids)
                    if result:
                        downloaded += 1
                        print(f"   ✅ [{i}/{len(uids_to_download)}] 下载: {result}")
                    else:
                        skipped += 1
                except Exception as e:
                    logger.error(f"下载邮件 UID {uid} 失败: {e}")
                    print(f"   ❌ [{i}/{len(uids_to_download)}] 下载失败: {e}")

            if downloaded > 0 or skipped > 0:
                print(f"\n📊 新下载 {downloaded} 封" + (f", 已有跳过 {skipped} 封" if skipped else ""))
            logger.info(f"邮件下载完成: 新下载 {downloaded}, 跳过 {skipped}")

            # 保存缓存
            self._save_fetch_cache(uidvalidity, max_uid)

            return downloaded

        except Exception as e:
            print(f"❌ 获取邮件时发生错误: {e}")
            logger.error(f"获取邮件失败: {e}")
            return 0

    def _batch_filter(self, uids: List[bytes], existing_message_ids: Set[str]) -> List[bytes]:
        """
        批量获取邮件头部，过滤主题并去重

        Args:
            uids: 待检查的 UID 列表
            existing_message_ids: 已存在的 Message-ID 集合

        Returns:
            需要下载的 UID 列表
        """
        if not uids:
            return []

        search_subject = config.IMAP_SEARCH_SUBJECT

        try:
            # 批量获取 Subject 和 Message-ID
            uid_range = b','.join(uids)
            status, batch_data = self.connection.uid(
                'fetch', uid_range,
                '(BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID)])'
            )
            if status != 'OK':
                logger.error("批量获取头部失败")
                return []

            uids_to_download = []
            matched_count = 0

            i = 0
            while i < len(batch_data):
                item = batch_data[i]
                if isinstance(item, tuple) and len(item) == 2:
                    meta = item[0].decode('utf-8', errors='replace')
                    uid_match = re.search(r'UID\s+(\d+)', meta)
                    if not uid_match:
                        i += 1
                        continue
                    uid_str = uid_match.group(1).encode()

                    raw_header = item[1]
                    if isinstance(raw_header, bytes):
                        raw_header = raw_header.decode('utf-8', errors='replace')

                    msg = email.message_from_string(raw_header)
                    subject = self._decode_header_value(msg.get('Subject', ''))
                    msg_id = msg.get('Message-ID', '').strip()

                    if search_subject in subject and '系统退信' not in subject:
                        matched_count += 1
                        if not msg_id or msg_id not in existing_message_ids:
                            uids_to_download.append(uid_str)

                i += 1

            logger.info(
                f"批量检查完成: 共{len(uids)}封, "
                f"匹配主题{matched_count}封, 需下载{len(uids_to_download)}封"
            )
            print(f"   ✅ 匹配 {matched_count} 封, 其中 {len(uids_to_download)} 封为新邮件")
            return uids_to_download

        except Exception as e:
            logger.error(f"批量过滤失败: {e}")
            return []

    def _get_existing_message_ids(self) -> Set[str]:
        """
        扫描本地已有 .eml 文件，提取 Message-ID 用于去重

        Returns:
            已有邮件的 Message-ID 集合
        """
        message_ids = set()

        try:
            for eml_file in self.save_dir.glob(f"*{config.EMAIL_FILE_EXTENSION}"):
                try:
                    with open(eml_file, 'r', encoding='utf-8', errors='replace') as f:
                        # 只读取前 50 行（头部信息），提高效率
                        lines = []
                        for i, line in enumerate(f):
                            if i >= 50:
                                break
                            lines.append(line)
                        header_text = ''.join(lines)

                    msg = email.message_from_string(header_text)
                    msg_id = msg.get('Message-ID', '').strip()
                    if msg_id:
                        message_ids.add(msg_id)
                except Exception as e:
                    logger.debug(f"读取 Message-ID 失败: {eml_file.name}, {e}")
                    continue

        except Exception as e:
            logger.error(f"扫描已有邮件失败: {e}")

        return message_ids

    def _download_email(self, uid: bytes, existing_message_ids: Set[str]) -> Optional[str]:
        """
        下载单封邮件并保存为 .eml 文件

        Args:
            uid: 邮件 UID
            existing_message_ids: 已存在的 Message-ID 集合

        Returns:
            保存的文件名，若跳过则返回 None
        """
        try:
            # 获取完整邮件内容
            status, data = self.connection.uid('fetch', uid, '(RFC822)')
            if status != 'OK' or not data or not data[0]:
                logger.warning(f"获取邮件内容失败: UID {uid}")
                return None

            raw_email = data[0][1]

            # 解析邮件获取头部信息
            msg = email.message_from_bytes(raw_email)

            # 检查 Message-ID 是否已存在
            msg_id = msg.get('Message-ID', '').strip()
            if msg_id and msg_id in existing_message_ids:
                return None

            # 解析主题和日期
            subject = self._decode_header_value(msg.get('Subject', ''))
            date_str = msg.get('Date', '')

            # 生成文件名
            filename = self._generate_filename(subject, date_str)
            if not filename:
                logger.warning(f"无法生成文件名: subject={subject}")
                return None

            # 检查文件是否已存在（按文件名去重）
            file_path = self.save_dir / filename
            if file_path.exists():
                # 将 Message-ID 加入集合，避免后续重复检查
                if msg_id:
                    existing_message_ids.add(msg_id)
                return None

            # 保存邮件
            with open(file_path, 'wb') as f:
                f.write(raw_email)

            # 记录 Message-ID
            if msg_id:
                existing_message_ids.add(msg_id)

            logger.info(f"已下载邮件: {filename}")
            return filename

        except Exception as e:
            logger.error(f"下载邮件 UID {uid} 时出错: {e}")
            return None

    def _generate_filename(self, subject: str, date_str: str) -> Optional[str]:
        """
        根据邮件主题生成规范文件名

        邮件主题格式示例：
        - XXX--工作日志[2024-10-15]--[提交成功]
        - XXX--工作日志[2024-10-15]--[提交成功](不够300字)
        - XXX--工作日志[2024-10-15]--[提交成功]_迟发补登

        Args:
            subject: 邮件主题
            date_str: 邮件日期字符串

        Returns:
            文件名字符串，失败返回 None
        """
        if not subject:
            return None

        # 清理主题中的特殊字符（保留中文、字母、数字和常用符号）
        cleaned = subject.strip()
        # 将 / 替换为 _（邮件主题用 /迟发补登，本地文件名用 _迟发补登）
        cleaned = cleaned.replace('/', '_')
        # 移除 Windows 文件名非法字符: \ : * ? " < > |
        cleaned = re.sub(r'[\\:*?"<>|]', '', cleaned)
        # 去除首尾空格
        cleaned = cleaned.strip()

        if not cleaned:
            return None

        filename = f"{cleaned}{config.EMAIL_FILE_EXTENSION}"
        return filename

    def _decode_header_value(self, value: str) -> str:
        """
        解码邮件头部值（处理 MIME 编码）

        Args:
            value: 原始头部值

        Returns:
            解码后的字符串
        """
        if not value:
            return ""

        try:
            decoded_parts = decode_header(value)
            result = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    candidate_encodings = []
                    if charset:
                        candidate_encodings.append(charset)
                        normalized = charset.lower()
                        # 一些旧邮件头会标成 gb2312，但实际字节需要 gbk/gb18030 才能完整解出。
                        if normalized in ('gb2312', 'gb_2312-80', 'gb2312-80'):
                            candidate_encodings.extend(['gbk', 'gb18030'])
                        elif normalized == 'gbk':
                            candidate_encodings.append('gb18030')

                    candidate_encodings.extend([config.DEFAULT_ENCODING, *config.FALLBACK_ENCODINGS, 'utf-8'])

                    decoded_text = None
                    seen = set()
                    for encoding in candidate_encodings:
                        if not encoding:
                            continue

                        normalized = encoding.lower()
                        if normalized in seen:
                            continue
                        seen.add(normalized)

                        try:
                            decoded_text = part.decode(encoding)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue

                    if decoded_text is None:
                        decoded_text = part.decode('utf-8', errors='replace')

                    result.append(decoded_text)
                else:
                    result.append(part)
            return ''.join(result)
        except Exception as e:
            logger.debug(f"解码头部值失败: {e}")
            return str(value)
