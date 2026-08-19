# -*- coding: utf-8 -*-

from .helpers import IMAGE_MAGIC_NUMBERS, MIN_READ_BYTES

# 常见文件类型的MIME映射
MIME_TYPES = {
    # 图片文件
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/bmp': 'bmp',
    'image/x-icon': 'ico',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'image/tiff': 'tiff',
    'image/jp2': 'jp2',
    'image/avif': 'avif',
    # 文档文件
    'application/pdf': 'pdf',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.ms-powerpoint': 'ppt',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    # 压缩文件
    'application/zip': 'zip',
    'application/x-rar-compressed': 'rar',
    'application/gzip': 'gz',
    'application/x-tar': 'tar',
    # 音频文件
    'audio/mpeg': 'mp3',
    'audio/wav': 'wav',
    'audio/ogg': 'ogg',
    'audio/flac': 'flac',
    # 视频文件
    'video/mp4': 'mp4',
    'video/avi': 'avi',
    'video/mpeg': 'mpeg',
    'video/quicktime': 'mov',
    # 文本文件
    'text/plain': 'txt',
    'text/html': 'html',
    'text/css': 'css',
    'application/javascript': 'js',
    'application/json': 'json',
    'text/xml': 'xml',
}


# 猜测文件的MIME类型
def guess_mime(data: bytes) -> str:
    """
    根据二进制数据猜测文件的MIME类型

    Args:
        data: 要检测的二进制数据

    Returns:
        str: 猜测的MIME类型，如果无法确定则返回空字符串
    """
    if not data or len(data) < 4:
        return ''

    # 截取足够长的数据用于检测
    sample = data[:MIN_READ_BYTES]

    # 检查所有已知的文件头
    for magic, mime_type in IMAGE_MAGIC_NUMBERS.items():
        # 检查数据长度是否足够
        if len(sample) < len(magic):
            continue

        # 检查文件头是否匹配
        if sample.startswith(magic):
            # 如果是函数（如WebP和AVIF的特殊检测），则调用函数进行进一步验证
            if callable(mime_type):
                if mime_type(data):
                    # 返回对应的MIME类型
                    if magic == b'RIFF':
                        return 'image/webp'
                    elif magic == b'ftypavif':
                        return 'image/avif'
            else:
                return mime_type

    # 检查其他常见文件类型
    # PDF文件
    if sample.startswith(b'%PDF'):
        return 'application/pdf'

    # ZIP文件
    if sample.startswith(b'PK\x03\x04') or sample.startswith(b'PK\x05\x06') or sample.startswith(b'PK\x07\x08'):
        return 'application/zip'

    # RAR文件
    if sample.startswith(b'Rar!'):
        return 'application/x-rar-compressed'

    # GZIP文件
    if sample.startswith(b'\x1f\x8b'):
        return 'application/gzip'

    # TAR文件
    if len(sample) >= 262 and sample[257:262] == b'ustar':
        return 'application/x-tar'

    # MP3文件（ID3v2标签）
    if sample.startswith(b'ID3'):
        return 'audio/mpeg'

    # MP4文件
    if sample.startswith(b'ftypisom') or sample.startswith(b'ftypmp42'):
        return 'video/mp4'

    # JSON文件（简单检测）
    if len(sample) >= 2:
        sample_str = sample.decode('utf-8', errors='ignore')
        if (sample_str.startswith('{') and sample_str.endswith('}')) or (
                sample_str.startswith('[') and sample_str.endswith(']')):
            try:
                import json
                json.loads(sample_str)
                return 'application/json'
            except:
                pass

    # XML文件（简单检测）
    if sample_str.startswith('<?xml') or sample_str.startswith('<') and '>' in sample_str:
        return 'text/xml'

    # 纯文本文件（启发式检测）
    try:
        # 尝试将数据解码为UTF-8文本
        sample.decode('utf-8')
        # 检查控制字符的比例
        control_chars = sum(1 for c in sample if c < 32 and c not in [9, 10, 13])
        if len(sample) > 0 and control_chars / len(sample) < 0.3:
            return 'text/plain'
    except:
        pass

    return ''


# 获取文件扩展名
def get_extension(mime_type: str) -> str:
    """
    根据MIME类型获取常见的文件扩展名

    Args:
        mime_type: MIME类型字符串

    Returns:
        str: 文件扩展名（不包含点号），如果未知则返回空字符串
    """
    return MIME_TYPES.get(mime_type.lower(), '')


# 猜测文件扩展名
def guess_extension(data: bytes) -> str:
    """
    根据二进制数据猜测文件扩展名

    Args:
        data: 要检测的二进制数据

    Returns:
        str: 猜测的文件扩展名（不包含点号），如果无法确定则返回空字符串
    """
    mime_type = guess_mime(data)
    return get_extension(mime_type)


# 检测是否为特定类型的文件
def is_type(data: bytes, mime_type: str) -> bool:
    """
    检测给定的二进制数据是否为指定类型的文件

    Args:
        data: 要检测的二进制数据
        mime_type: 要检测的MIME类型

    Returns:
        bool: 如果是指定类型返回True，否则返回False
    """
    guessed_mime = guess_mime(data)
    return guessed_mime == mime_type
