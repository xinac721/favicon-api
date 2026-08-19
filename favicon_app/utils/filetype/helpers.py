# -*- coding: utf-8 -*-

import struct

# 图片文件的魔术数字（文件头）
IMAGE_MAGIC_NUMBERS = {
    # JPEG
    b'\xff\xd8\xff': 'image/jpeg',
    # PNG
    b'\x89PNG\r\n\x1a\n': 'image/png',
    # GIF
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    # BMP
    b'BM': 'image/bmp',
    # ICO
    b'\x00\x00\x01\x00': 'image/x-icon',
    # WebP
    b'RIFF': lambda data: _is_webp(data) if len(data) >= 12 else False,
    # SVG (基于XML)
    b'<?xml': 'image/svg+xml',
    b'<svg': 'image/svg+xml',
    # TIFF
    b'II\x2a\x00': 'image/tiff',
    b'MM\x00\x2a': 'image/tiff',
    # JPEG2000
    b'\x00\x00\x00\x0cjP\x1a\x00\x00\x00\x00\x00': 'image/jp2',
    # AVIF
    b'ftypavif': lambda data: _is_avif(data) if len(data) >= 12 else False,
}

# 最小需要读取的字节数，确保能检测所有支持的文件类型
MIN_READ_BYTES = 32


# 检测是否为WebP文件
def _is_webp(data: bytes) -> bool:
    if len(data) < 12:
        return False
    # WebP文件格式：RIFF[4字节长度]WEBP
    return data[8:12] == b'WEBP'


# 检测是否为AVIF文件
def _is_avif(data: bytes) -> bool:
    if len(data) < 12:
        return False
    # AVIF文件格式：ftypavif[4字节版本]...
    return data[4:12] == b'ftypavif' or data[4:12] == b'ftypavis'


# 检测数据是否为图片文件
def is_image(data: bytes) -> bool:
    """
    检测给定的二进制数据是否为图片文件

    Args:
        data: 要检测的二进制数据

    Returns:
        bool: 如果是图片文件返回True，否则返回False
    """
    if not data or len(data) < 4:
        return False

    # 截取足够长的数据用于检测
    sample = data[:MIN_READ_BYTES]

    # 检查所有已知的图片文件头
    for magic, mime_type in IMAGE_MAGIC_NUMBERS.items():
        # 检查数据长度是否足够
        if len(sample) < len(magic):
            continue

        # 检查文件头是否匹配
        if sample.startswith(magic):
            # 如果是函数（如WebP和AVIF的特殊检测），则调用函数进行进一步验证
            if callable(mime_type):
                if mime_type(data):
                    return True
            else:
                return True

    # 检查是否为某些特殊格式的图片
    # 例如一些可能缺少标准文件头的图片
    try:
        # 检查是否为常见图片宽度/高度字段的位置
        # 这是一个启发式方法，不是100%准确
        if len(data) >= 24:
            # 检查JPEG的SOF marker后的尺寸信息
            for i in range(4, len(data) - 16):
                if data[i] == 0xFF and data[i + 1] in [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD,
                                                       0xCE, 0xCF]:
                    # 找到SOF marker，尝试读取高度和宽度
                    if i + 8 < len(data):
                        height = struct.unpack('!H', data[i + 5:i + 7])[0]
                        width = struct.unpack('!H', data[i + 7:i + 9])[0]
                        # 合理的图片尺寸
                        if 1 <= height <= 10000 and 1 <= width <= 10000:
                            return True
    except Exception:
        pass

    return False
