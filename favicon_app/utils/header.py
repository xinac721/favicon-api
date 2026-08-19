# -*- coding: utf-8 -*-

import logging
import random
import threading
from typing import Dict, Optional

# 配置日志
logger = logging.getLogger(__name__)


class HeaderConfig:
    """HTTP请求头管理类，提供灵活的请求头配置和生成功能"""

    _USER_AGENTS = [
        # Firefox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:112.0) Gecko/20100101 Firefox/112.0',
        'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:110.0) Gecko/20100101 Firefox/110.0',
        # Chrome
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.63 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        # Edge
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.53',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.102 Safari/537.36 Edg/104.0.1293.63',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.70',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.134 Safari/537.36 Edg/103.0.1264.77',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.62',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.78',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.58',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0',
        # macOS
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        # iOS
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1',
        # Android
        'Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36'
    ]

    # 合并两个版本的图片类型，并添加更多常见的图片格式
    IMAGE_TYPES = [
        'image/gif',
        'image/jpeg',
        'image/png',
        'image/svg+xml',
        'image/tiff',
        'image/vnd.wap.wbmp',
        'image/webp',
        'image/x-icon',
        'image/x-jng',
        'image/x-ms-bmp',
        'image/vnd.microsoft.icon',
        'image/vnd.dwg',
        'image/vnd.dxf',
        'image/jpx',
        'image/apng',
        'image/bmp',
        'image/vnd.ms-photo',
        'image/vnd.adobe.photoshop',
        'image/heic',
        'image/avif',
        'image/jfif',
        'image/pjpeg',
        'image/vnd.adobe.illustrator',
        'application/pdf',
        'application/x-pdf'
    ]

    # 默认内容类型
    CONTENT_TYPE = 'application/json; charset=utf-8'

    # 不同场景的请求头模板
    _HEADER_TEMPLATES = {
        'default': {
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Accept-Encoding': 'gzip, deflate',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Connection': 'keep-alive'
        },
        'image': {
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        },
        'api': {
            'Accept': 'application/json, application/xml',
            'Content-Type': CONTENT_TYPE,
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
    }

    def __init__(self):
        # 线程锁，确保线程安全
        self._lock = threading.RLock()
        # 存储自定义请求头
        self._custom_headers = {}

    def get_random_user_agent(self) -> str:
        """获取随机的User-Agent字符串"""
        with self._lock:
            return random.choice(self._USER_AGENTS)

    def get_headers(
            self,
            template: str = 'default',
            include_user_agent: bool = True,
            custom_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        获取配置好的请求头字典
        
        Args:
            template: 请求头模板类型，可选值：'default', 'image', 'api'
            include_user_agent: 是否包含随机User-Agent
            custom_headers: 自定义请求头，将覆盖默认值
            
        Returns:
            配置好的请求头字典
        """
        with self._lock:
            # 选择基础模板
            headers = self._HEADER_TEMPLATES.get(template, self._HEADER_TEMPLATES['default']).copy()

            # 添加随机User-Agent
            if include_user_agent:
                headers['User-Agent'] = self.get_random_user_agent()

            # 添加自定义请求头
            if self._custom_headers:
                headers.update(self._custom_headers)

            # 添加方法参数中的自定义请求头
            if custom_headers:
                headers.update(custom_headers)

            return headers

    def set_custom_header(self, key: str, value: str) -> None:
        """设置自定义请求头，将应用于所有后续生成的请求头"""
        if not key or not value:
            logger.warning("尝试设置空的请求头键或值")
            return

        with self._lock:
            self._custom_headers[key] = value
            logger.debug(f"已设置自定义请求头: {key} = {value}")

    def remove_custom_header(self, key: str) -> None:
        """移除自定义请求头"""
        with self._lock:
            if key in self._custom_headers:
                del self._custom_headers[key]
                logger.debug(f"已移除自定义请求头: {key}")

    def clear_custom_headers(self) -> None:
        """清除所有自定义请求头"""
        with self._lock:
            self._custom_headers.clear()
            logger.debug("已清除所有自定义请求头")

    def is_image_content_type(self, content_type: str) -> bool:
        """检查内容类型是否为图片类型"""
        if not content_type:
            return False

        # 处理可能包含参数的Content-Type，如 'image/png; charset=utf-8'
        base_type = content_type.split(';')[0].strip().lower()
        return base_type in self.IMAGE_TYPES

    def add_user_agent(self, user_agent: str) -> None:
        """添加自定义User-Agent到池"""
        if not user_agent or user_agent in self._USER_AGENTS:
            return

        with self._lock:
            self._USER_AGENTS.append(user_agent)
            logger.debug(f"已添加自定义User-Agent")

    def get_specific_headers(
            self,
            url: str = None,
            referer: str = None,
            content_type: str = None
    ) -> Dict[str, str]:
        """
        获取针对特定场景优化的请求头
        
        Args:
            url: 目标URL，用于设置Host
            referer: 引用页URL
            content_type: 内容类型
            
        Returns:
            优化后的请求头字典
        """
        headers = self.get_headers()

        # 设置Host
        if url:
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(url)
                if parsed_url.netloc:
                    headers['Host'] = parsed_url.netloc
            except Exception as e:
                logger.warning(f"解析URL失败: {e}")

        # 设置Referer
        if referer:
            headers['Referer'] = referer

        # 设置Content-Type
        if content_type:
            headers['Content-Type'] = content_type

        return headers


# 创建全局HeaderConfig实例，用于向后兼容
_header_config = HeaderConfig()

# 全局请求头字典，用于向后兼容
_headers = {'User-Agent': '-'}

# 向后兼容的常量和函数
content_type = HeaderConfig.CONTENT_TYPE
image_type = HeaderConfig.IMAGE_TYPES


def get_header():
    """向后兼容的函数：获取请求头"""
    global _headers
    _headers = _header_config.get_headers(template='default')
    return _headers


def set_header(key: str, value: str):
    """向后兼容的函数：设置请求头"""
    if key and value:
        _header_config.set_custom_header(key, value)


def del_header(key: str):
    """向后兼容的函数：删除请求头"""
    _header_config.remove_custom_header(key)


def get_user_agent():
    """向后兼容的函数：获取请求头中的User-Agent"""
    return _headers.get('User-Agent', '')


def set_user_agent(ua: str):
    """向后兼容的函数：设置请求头中的User-Agent"""
    if ua:
        _header_config.set_custom_header('User-Agent', ua)
