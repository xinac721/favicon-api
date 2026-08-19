# -*- coding: utf-8 -*-

import re

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
    # TIFF
    b'II\x2a\x00': 'image/tiff',
    b'MM\x00\x2a': 'image/tiff',
    # JPEG2000
    b'\x00\x00\x00\x0cjP\x1a\x00\x00\x00\x00\x00': 'image/jp2',
}

# 最小需要读取的字节数，确保能检测所有支持的文件类型
MIN_READ_BYTES = 32


# 检测是否为WebP文件
def _is_webp(data: bytes) -> bool:
    if len(data) < 12:
        return False
    # WebP文件格式：RIFF[4字节长度]WEBP
    return data[8:12] == b'WEBP'


def is_svg(data: bytes) -> bool:
    """Recognize an SVG root element without treating arbitrary XML as SVG."""
    if not data:
        return False
    prefix = data[:4096].decode('utf-8-sig', errors='ignore').lstrip()
    prefix = re.sub(r'^(?:<\?xml[^>]*>\s*)?', '', prefix, flags=re.I)
    prefix = re.sub(r'^(?:<!--.*?-->\s*)*', '', prefix, flags=re.I | re.S)
    prefix = re.sub(r'^(?:<!doctype\s+svg[^>]*>\s*)?', '', prefix, flags=re.I | re.S)
    return re.match(r'<svg(?:\s|>)', prefix, flags=re.I) is not None


def is_avif(data: bytes) -> bool:
    """Check AVIF major and compatible brands in the ISO-BMFF ftyp box."""
    if len(data) < 16 or data[4:8] != b'ftyp':
        return False
    box_size = int.from_bytes(data[:4], byteorder='big')
    if box_size < 16:
        return False
    box = data[:min(box_size, len(data), 256)]
    brands = [box[8:12]]
    brands.extend(box[offset:offset + 4] for offset in range(16, len(box) - 3, 4))
    return any(brand in (b'avif', b'avis') for brand in brands)


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

    if is_svg(data):
        return True
    if is_avif(data):
        return True

    # 截取足够长的数据用于检测
    sample = data[:MIN_READ_BYTES]

    # 检查所有已知的图片文件头
    for magic, mime_type in IMAGE_MAGIC_NUMBERS.items():
        # 检查数据长度是否足够
        if len(sample) < len(magic):
            continue

        # 检查文件头是否匹配
        if sample.startswith(magic):
            # WebP 等格式需要调用函数进一步验证
            if callable(mime_type):
                if mime_type(data):
                    return True
            else:
                return True

    return False
