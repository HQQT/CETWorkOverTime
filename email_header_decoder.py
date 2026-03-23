"""
邮件头解码工具模块
"""

import logging
from email.header import decode_header
from typing import List

import config

logger = logging.getLogger(__name__)

_GB2312_ALIASES = {"gb2312", "gb_2312-80", "gb2312-80"}


def _build_candidate_encodings(charset: str | None) -> List[str]:
    candidate_encodings: List[str] = []
    if charset:
        candidate_encodings.append(charset)
        normalized = charset.lower()
        if normalized in _GB2312_ALIASES:
            candidate_encodings.extend(["gbk", "gb18030"])
        elif normalized == "gbk":
            candidate_encodings.append("gb18030")

    candidate_encodings.extend(
        [config.DEFAULT_ENCODING, *config.FALLBACK_ENCODINGS, "utf-8"]
    )
    return candidate_encodings


def decode_mime_header(value: str) -> str:
    """
    解码 MIME 邮件头，兼容错误标注为 gb2312 的旧邮件。

    Args:
        value: 原始邮件头字符串

    Returns:
        解码后的字符串
    """
    if not value:
        return ""

    try:
        result: List[str] = []
        for part, charset in decode_header(value):
            if not isinstance(part, bytes):
                result.append(str(part))
                continue

            decoded_text = None
            seen = set()
            for encoding in _build_candidate_encodings(charset):
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
                decoded_text = part.decode("utf-8", errors="replace")

            result.append(decoded_text)

        return "".join(result).strip()
    except Exception as exc:
        logger.debug(f"解码邮件头失败: {exc}")
        return str(value).strip()
