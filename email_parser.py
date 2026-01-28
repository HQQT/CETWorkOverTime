"""
邮件解析器模块
"""

import email
import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Dict, Any
import chardet

import config
from date_utils import DateUtils

logger = logging.getLogger(__name__)


class EmailData:
    """邮件数据类"""
    
    def __init__(self):
        self.filename: str = ""
        self.date: Optional[object] = None
        self.subject: str = ""
        self.sender: str = ""
        self.content: str = ""
        self.raw_content: str = ""
        self.file_path: Path = None
        
    def __str__(self):
        return f"EmailData(filename={self.filename}, date={self.date}, subject={self.subject[:50]}...)"


class EmailParser:
    """邮件解析器类"""
    
    def __init__(self):
        self.date_utils = DateUtils()
    
    def parse_email_file(self, file_path: Path) -> Optional[EmailData]:
        """
        解析单个邮件文件
        
        Args:
            file_path: 邮件文件路径
            
        Returns:
            EmailData对象，如果解析失败返回None
        """
        try:
            logger.info(f"开始解析邮件文件: {file_path.name}")
            
            # 检查文件是否应该被排除
            if self.date_utils.should_exclude_file(file_path.name):
                logger.info(f"跳过排除的文件: {file_path.name}")
                return None
            
            # 读取文件内容
            raw_content = self._read_file_with_encoding(file_path)
            if not raw_content:
                logger.error(f"无法读取文件内容: {file_path}")
                return None
            
            # 解析邮件
            email_msg = email.message_from_string(raw_content)
            
            # 创建邮件数据对象
            email_data = EmailData()
            email_data.filename = file_path.name
            email_data.file_path = file_path
            email_data.raw_content = raw_content
            
            # 提取基本信息
            email_data.subject = self._decode_header(email_msg.get('Subject', ''))
            email_data.sender = self._decode_header(email_msg.get('From', ''))
            
            # 提取日期（优先从文件名，其次从邮件头）
            email_data.date = self.date_utils.extract_date_from_filename(file_path.name)
            if not email_data.date:
                email_date = email_msg.get('Date', '')
                if email_date:
                    email_data.date = self.date_utils.extract_date_from_email_header(email_date)
            
            if not email_data.date:
                logger.warning(f"无法提取邮件日期: {file_path.name}")
                return None
            
            # 检查日期有效性
            if not self.date_utils.is_valid_work_date(email_data.date):
                logger.warning(f"无效的工作日期: {email_data.date} in {file_path.name}")
                return None
            
            # 提取邮件正文
            email_data.content = self._extract_email_content(email_msg)
            
            if not email_data.content.strip():
                logger.warning(f"邮件内容为空: {file_path.name}")
                return None
            
            logger.info(f"成功解析邮件: {file_path.name}, 日期: {email_data.date}")
            return email_data
            
        except Exception as e:
            logger.error(f"解析邮件文件时发生错误: {file_path}, 错误: {e}")
            return None
    
    def _read_file_with_encoding(self, file_path: Path) -> Optional[str]:
        """
        使用合适的编码读取文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容字符串，如果读取失败返回None
        """
        try:
            # 首先尝试检测编码
            with open(file_path, 'rb') as f:
                raw_data = f.read()
            
            detected = chardet.detect(raw_data)
            encoding = detected.get('encoding', config.DEFAULT_ENCODING)
            
            # 尝试使用检测到的编码
            try:
                return raw_data.decode(encoding)
            except UnicodeDecodeError:
                logger.warning(f"检测到的编码 {encoding} 解码失败，尝试备用编码")
            
            # 尝试备用编码
            for enc in [config.DEFAULT_ENCODING] + config.FALLBACK_ENCODINGS:
                try:
                    return raw_data.decode(enc)
                except UnicodeDecodeError:
                    continue
            
            logger.error(f"所有编码尝试失败: {file_path}")
            return None
            
        except Exception as e:
            logger.error(f"读取文件时发生错误: {file_path}, 错误: {e}")
            return None
    
    def _decode_header(self, header_value: str) -> str:
        """
        解码邮件头信息
        
        Args:
            header_value: 邮件头值
            
        Returns:
            解码后的字符串
        """
        try:
            if not header_value:
                return ""
            
            decoded_parts = email.header.decode_header(header_value)
            result = ""
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        result += part.decode(encoding)
                    else:
                        # 尝试常用编码
                        for enc in [config.DEFAULT_ENCODING] + config.FALLBACK_ENCODINGS:
                            try:
                                result += part.decode(enc)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            result += part.decode('utf-8', errors='ignore')
                else:
                    result += str(part)
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"解码邮件头时发生错误: {header_value}, 错误: {e}")
            return header_value
    
    def _extract_email_content(self, email_msg: EmailMessage) -> str:
        """
        提取邮件正文内容
        
        Args:
            email_msg: 邮件消息对象
            
        Returns:
            邮件正文内容
        """
        try:
            content = ""
            
            if email_msg.is_multipart():
                # 多部分邮件
                for part in email_msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            content += self._decode_payload(payload, part)
            else:
                # 单部分邮件
                payload = email_msg.get_payload(decode=True)
                if payload:
                    content = self._decode_payload(payload, email_msg)
            
            # 清理和格式化内容
            return self._clean_content(content)
            
        except Exception as e:
            logger.error(f"提取邮件内容时发生错误: {e}")
            return ""
    
    def _decode_payload(self, payload: bytes, part: EmailMessage) -> str:
        """
        解码邮件载荷
        
        Args:
            payload: 邮件载荷字节
            part: 邮件部分对象
            
        Returns:
            解码后的字符串
        """
        try:
            # 获取字符集
            charset = part.get_content_charset()
            if charset:
                return payload.decode(charset)
            
            # 尝试常用编码
            for encoding in [config.DEFAULT_ENCODING] + config.FALLBACK_ENCODINGS:
                try:
                    return payload.decode(encoding)
                except UnicodeDecodeError:
                    continue
            
            # 最后尝试忽略错误
            return payload.decode('utf-8', errors='ignore')
            
        except Exception as e:
            logger.error(f"解码载荷时发生错误: {e}")
            return ""
    
    def _clean_content(self, content: str) -> str:
        """
        清理邮件内容

        Args:
            content: 原始内容

        Returns:
            清理后的内容
        """
        if not content:
            return ""

        # 智能处理Unicode转义序列
        # 只有当内容中包含 \uXXXX 格式的Unicode转义序列时才进行解码
        # 避免对正常UTF-8编码的中文内容造成乱码
        import re
        if re.search(r'\\u[0-9a-fA-F]{4}', content):
            try:
                content = content.encode('utf-8').decode('unicode_escape')
            except:
                # 如果解码失败，保持原内容
                pass

        lines = content.split('\n')
        cleaned_lines = []

        # 查找内容开始和结束标记
        start_found = False

        for line in lines:
            line = line.strip()

            # 跳过空行
            if not line:
                if start_found:
                    cleaned_lines.append("")
                continue

            # 检查是否为内容开始标记
            if not start_found:
                for marker in config.CONTENT_START_MARKERS:
                    if marker in line:
                        start_found = True
                        cleaned_lines.append(line)
                        break
                continue

            # 检查是否为内容结束标记
            # 要求行以结束标记开头，或者是特定的分隔格式，避免误判正文中的"工作计划"等词
            is_end = False
            for marker in config.CONTENT_END_MARKERS:
                # 行以标记开头，或者行以 "[以下是" 或 "---" 等分隔符开头
                if line.startswith(marker) or line.startswith("[以下是") or line.startswith("---"):
                    is_end = True
                    break

            if is_end:
                break

            cleaned_lines.append(line)

        # 如果没有找到开始标记，返回所有内容
        if not start_found:
            cleaned_lines = [line.strip() for line in lines if line.strip()]

        return '\n'.join(cleaned_lines).strip()
