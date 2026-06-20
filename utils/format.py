"""格式化工具函数"""

import gzip
import json
import zlib


def format_size(size: int) -> str:
    """格式化文件大小"""
    if size == 0:
        return "0B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(size) < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def format_duration(seconds: float) -> str:
    """格式化耗时"""
    if seconds < 0.001:
        return f"{seconds*1000000:.0f}μs"
    elif seconds < 1:
        return f"{seconds*1000:.1f}ms"
    else:
        return f"{seconds:.2f}s"


def is_text_content(content_type: str) -> bool:
    """判断是否为文本类型内容"""
    if not content_type:
        return False
    text_types = [
        'text/', 'application/json', 'application/xml', 'application/javascript',
        'application/x-www-form-urlencoded',
    ]
    for t in text_types:
        if t in content_type.lower():
            return True
    return False


def _try_decompress(data: bytes) -> str:
    """尝试解压缩并解码为文本，失败返回 None"""
    # gzip: magic bytes 1f 8b
    if data[:2] == b'\x1f\x8b':
        try:
            return gzip.decompress(data).decode('utf-8')
        except Exception:
            pass

    # brotli
    try:
        import brotli
        return brotli.decompress(data).decode('utf-8')
    except Exception:
        pass

    # deflate (raw)
    try:
        return zlib.decompress(data, -zlib.MAX_WBITS).decode('utf-8')
    except Exception:
        pass

    # deflate (wrapped)
    try:
        return zlib.decompress(data).decode('utf-8')
    except Exception:
        pass

    return None


def format_body(body: bytes, content_type: str = None) -> str:
    """格式化 body 内容（完整保留，不截断）"""
    if not body:
        return "(empty)"

    size = len(body)

    # 判断是否为文本类型
    if content_type and not is_text_content(content_type):
        return f"({format_size(size)} binary data)"

    # 尝试解码为文本（完整保留）
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        # UTF-8 解码失败，尝试解压缩后再解码
        text = _try_decompress(body)

    if text is None:
        return f"({format_size(size)} binary data)"

    # 尝试格式化 JSON
    if content_type and 'json' in content_type.lower():
        try:
            obj = json.loads(text)
            text = json.dumps(obj, indent=2, ensure_ascii=False)
        except:
            pass

    return text