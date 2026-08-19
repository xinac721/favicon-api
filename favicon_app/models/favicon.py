# -*- coding: utf-8 -*-

import base64
import hashlib
import ipaddress
import logging
import os
import re
import socket
import time
from typing import Tuple, Optional
from urllib.parse import urlparse, unquote

import aiohttp
import requests
import urllib3

import setting
from favicon_app.utils import header
from favicon_app.utils.file_util import FileUtil
from favicon_app.utils.filetype import helpers, filetype

urllib3.disable_warnings()
logging.captureWarnings(True)
logger = logging.getLogger(__name__)

# 创建requests会话池
requests_session = requests.Session()
requests_session.max_redirects = 3
requests_session.verify = False

# 请求超时设置
DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 2

# 临时存储域名和对应的MD5值
domain_md5_mapping = dict()

# 创建aiohttp客户端会话池
_aiohttp_client = None


class Favicon:
    """Favicon类，用于处理网站图标的获取和解析
    
    主要功能：
    - 解析URL，提取协议、域名和端口
    - 检查域名是否为内网地址
    - 获取网站图标URL和内容
    - 处理不同类型的图标路径
    
    Attributes:
        scheme: 协议类型(http/https)
        domain: 域名
        port: 端口号
        domain_md5: 域名的MD5哈希值
        icon_url: 图标URL
        path: 访问路径
    """
    # 协议://域名:端口号, 域名md5值
    scheme: Optional[str] = None
    domain: Optional[str] = None
    port: Optional[int] = None
    domain_md5: Optional[str] = None
    icon_url: Optional[str] = None
    # 访问路径
    path: str = '/'

    def __init__(self, url: str):
        """初始化Favicon对象
        
        Args:
            url: 要处理的URL字符串
        """
        try:
            url = url.lower().strip()
            self._parse(url)
            # 如果域名解析失败，尝试添加协议前缀
            if not self.domain_md5 and ('.' in url):
                if url.startswith('//'):
                    self._parse('http:' + url)
                elif not (url.startswith('https://') or url.startswith('http://')):
                    self._parse('http://' + url)
        except Exception as e:
            logger.error('初始化错误: %s, URL: %s', str(e), url)

    def _parse(self, url: str):
        """解析URL，提取协议、域名、路径和端口
        
        Args:
            url: 要解析的URL字符串
        """
        try:
            _url = urlparse(url)
            self.scheme = _url.scheme
            self.domain = _url.hostname
            self.path = _url.path
            self.port = _url.port

            # 处理协议
            if self.scheme not in ['https', 'http']:
                if self.scheme:
                    logger.warning('不支持的协议类型: %s', self.scheme)
                self.scheme = 'http'

            # 检查域名合法性
            if self.domain and not _check_url(self.domain):
                self.domain = None

            # 生成域名MD5哈希值
            if self.domain:
                self.domain_md5 = hashlib.md5(self.domain.encode("utf-8")).hexdigest()
        except Exception as e:
            add_failed_url(self.domain)
            self.scheme = None
            self.domain = None
            logger.error('URL解析错误: %s, URL: %s', str(e), url)

    def _get_icon_url(self, icon_path: str):
        """根据图标路径生成完整的图标URL
        
        Args:
            icon_path: 图标路径
        """
        if not icon_path or not self.domain or not self.scheme:
            self.icon_url = None
            return

        if icon_path.startswith(('https://', 'http://')):
            self.icon_url = icon_path
        elif icon_path.startswith('//'):
            self.icon_url = f"{self.scheme}:{icon_path}"
        elif icon_path.startswith('/'):
            self.icon_url = f"{self.scheme}://{self.domain}{icon_path}"
        elif icon_path.startswith('..'):
            clean_path = icon_path.replace('../', '')
            self.icon_url = f"{self.scheme}://{self.domain}/{clean_path}"
        elif icon_path.startswith('./'):
            self.icon_url = f"{self.scheme}://{self.domain}{icon_path[1:]}"
        elif icon_path.startswith('data:image'):
            self.icon_url = icon_path
        else:
            self.icon_url = f"{self.scheme}://{self.domain}/{icon_path}"

    def _get_icon_default(self):
        """获取网站默认favicon.ico路径
        """
        if self.domain and self.scheme:
            self.icon_url = f"{self.scheme}://{self.domain}/favicon.ico"
        else:
            self.icon_url = None

    def get_icon_url(self, icon_path: str, default: bool = False) -> Optional[str]:
        """获取图标URL
        
        Args:
            icon_path: 图标路径
            default: 是否使用默认图标路径
            
        Returns:
            完整的图标URL
        """
        if default:
            self._get_icon_default()
        else:
            self._get_icon_url(icon_path)
        return self.icon_url

    def get_base_url(self) -> Optional[str]:
        """获取网站基础URL

        Returns:
            网站基础URL
        """
        if not self.domain or '.' not in self.domain:
            return None

        _url = f"{self.scheme}://{self.domain}"
        if self.port and self.port not in [80, 443]:
            _url += f":{self.port}"

        return _url

    async def get_icon_file(self, icon_path: str, default: bool = False) -> Tuple[Optional[bytes], Optional[str]]:
        """获取图标文件内容和类型
        
        Args:
            icon_path: 图标路径
            default: 是否使用默认图标路径
            
        Returns:
            元组(图标内容, 内容类型)
        """
        self.get_icon_url(icon_path, default)

        if not self.icon_url or not self.domain or '.' not in self.domain:
            return None, None

        _content, _ct = None, None
        try:
            # 处理base64编码的图片
            if self.icon_url.startswith('data:image'):
                data_uri = self.icon_url.split(',')
                if len(data_uri) == 2:
                    if 'svg+xml,' in self.icon_url:
                        _content = unquote(data_uri[-1])
                    elif 'base64,' in self.icon_url:
                        _content = base64.b64decode(data_uri[-1])
                    if ';' in self.icon_url:
                        _ct = data_uri[0].split(';')[0].split(':')[-1]
                    else:
                        _ct = data_uri[0].split(':')[-1]
            else:
                _content, _ct = await _req_get(self.icon_url, domain=self.domain)

            # 验证是否为图片
            # image/* application/x-ico
            # if _ct and ('image' in _ct or 'ico' in _ct or helpers.is_image(_content)):
            if _ct and _content and helpers.is_image(_content):
                # 检查文件大小
                if len(_content) > 5 * 1024 * 1024:
                    logger.warning('图片过大: %d bytes, 域名: %s', len(_content), self.domain)
                return _content, filetype.guess_mime(_content) or _ct
        except Exception as e:
            logger.error('获取图标文件失败: %s, URL: %s', str(e), self.icon_url)

        return None, None

    async def req_get(self) -> Optional[bytes]:
        """获取网站首页内容
        
        Returns:
            网站首页HTML内容
        """
        if not self.domain or '.' not in self.domain:
            return None

        _url = self.get_base_url()
        _content, _ct = await _req_get(_url, domain=self.domain)

        # 验证类型并检查大小
        if _ct and ('text' in _ct or 'html' in _ct or 'xml' in _ct):
            if _content and len(_content) > 30 * 1024 * 1024:
                logger.error('页面内容过大: %d bytes, URL: %s', len(_content), _url)
                return None
            return _content

        return None


def _check_internal(domain: str) -> bool:
    """检查网址是否非内网地址

    Args:
        domain: 域名

    Returns:
        True: 非内网；False: 是内网/无法解析
    """
    try:
        # 检查是否为IP地址
        if domain.replace('.', '').isdigit():
            return not ipaddress.ip_address(domain).is_private
        else:
            # 解析域名获取IP地址
            ips = socket.getaddrinfo(domain, None)
            for ip_info in ips:
                ip = ip_info[4][0]
                if '.' in ip:
                    if not ipaddress.ip_address(ip).is_private:
                        return True
            return False
    except Exception as e:
        add_failed_url(domain)
        logger.error('解析域名出错: %s, 错误: %s', domain, str(e))
        return False


def _check_url(domain: str) -> bool:
    """检查域名是否合法且非内网地址

    Args:
        domain: 域名

    Returns:
        域名是否合法且非内网地址
    """
    return _pattern_domain.match(domain) and _check_internal(domain)


async def _req_get(url: str,
                   domain: str,
                   retries: int = DEFAULT_RETRIES,
                   timeout: int = DEFAULT_TIMEOUT) -> Tuple[Optional[bytes], Optional[str]]:
    """异步发送HTTP GET请求获取内容

    Args:
        url: 请求URL
        retries: 重试次数
        timeout: 超时时间(秒)

    Returns:
        元组(内容, 内容类型)
    """
    global _aiohttp_client
    logger.debug('发送异步请求: %s', url)

    # 初始化aiohttp客户端会话
    if _aiohttp_client is None:
        _aiohttp_client = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(verify_ssl=False, limit=1000),
            timeout=aiohttp.ClientTimeout(total=timeout),
            raise_for_status=False
        )

    retry_count = 0
    while retry_count <= retries:
        try:
            async with _aiohttp_client.get(
                    url,
                    headers=header.get_header(),
                    allow_redirects=True,
                    timeout=timeout,
            ) as resp:
                if resp.ok:
                    ct_type = resp.headers.get('Content-Type')
                    ct_length = resp.headers.get('Content-Length')

                    # 处理Content-Type
                    if ct_type and ';' in ct_type:
                        _cts = ct_type.split(';')
                        if 'charset' in _cts[0]:
                            ct_type = _cts[-1].strip()
                        else:
                            ct_type = _cts[0].strip()

                    # 检查响应大小
                    if ct_length and int(ct_length) > 10 * 1024 * 1024:
                        logger.warning('响应过大: %d bytes, URL: %s', int(ct_length), url)

                    content = await resp.read()
                    return content, ct_type
                else:
                    add_failed_url(domain)
                    logger.error('异步请求失败: %d, URL: %s', resp.status, url)
                    break
        except (aiohttp.ClientConnectorError, aiohttp.ServerTimeoutError) as e:
            retry_count += 1
            if retry_count > retries:
                add_failed_url(domain)
                logger.error('异步请求超时: %s, URL: %s', str(e), url)
            else:
                logger.warning('异步请求超时，正在重试(%d/%d): %s', retry_count, retries, url)
                continue
        except Exception as e:
            add_failed_url(domain)
            logger.error('异步请求异常: %s, URL: %s', str(e), url)
            break

    return None, None


def add_failed_url(domain: str):
    """添加失败的URL，将其保存为单独的文件

    Args:
        domain: 域名
    """
    # 确保域名不为空
    if not domain:
        return

    try:
        # 将域名的MD5值作为文件名
        domain_md5 = hashlib.md5(domain.encode("utf-8")).hexdigest()
        file_path = os.path.join(setting.failed_urls_dir, domain_md5[:1], f"{domain_md5}.txt")

        # 确保失败URL目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 格式化当前时间
        formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

        # 写入域名和时间到文件
        FileUtil.write_file(file_path, f"{domain}--{formatted_time}")

        # 缓存域名和MD5的映射关系
        domain_md5_mapping[domain] = domain_md5

        logger.debug('成功添加失败URL到文件: %s', domain)
    except Exception as e:
        logger.error('添加失败URL到文件出错: %s, 域名: %s', str(e), domain)


def is_failed_url(domain: str) -> bool:
    """检查域名是否是失败URL（未过期）
    
    Args:
        domain: 域名
        
    Returns:
        True: 是失败URL（未过期）；False: 不是失败URL或已过期
    """
    try:
        # 从缓存中获取域名的MD5值，如果没有则计算
        if domain in domain_md5_mapping:
            domain_md5 = domain_md5_mapping[domain]
        else:
            domain_md5 = hashlib.md5(domain.encode("utf-8")).hexdigest()
            domain_md5_mapping[domain] = domain_md5

        file_path = os.path.join(setting.failed_urls_dir, domain_md5[:1], f"{domain_md5}.txt")

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return False

        # 获取文件的修改时间
        file_mtime = os.path.getmtime(file_path)
        current_time = time.time()

        # 检查文件是否未过期
        if current_time - file_mtime <= setting.FAILED_URL_EXPIRE_TIME:
            return True
        else:
            try:
                os.remove(file_path)
                if domain in domain_md5_mapping:
                    del domain_md5_mapping[domain]
            except:
                pass
            return False
    except Exception as e:
        logger.error('检查失败URL出错: %s, 域名: %s', str(e), domain)
        return False


# 域名验证正则表达式
_pattern_domain = re.compile(
    r'[a-zA-Z0-9\u4E00-\u9FA5][-a-zA-Z0-9\u4E00-\u9FA5]{0,62}(\.[a-zA-Z0-9\u4E00-\u9FA5][-a-zA-Z0-9\u4E00-\u9FA5]{0,62})+\.?',
    re.I)
