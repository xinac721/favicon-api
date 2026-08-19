# -*- coding: utf-8 -*-

import hashlib
import logging
import os
import random
import re
import time
import warnings
from typing import Tuple, Optional

import bs4
import urllib3
from bs4 import XMLParsedAsHTMLWarning, SoupStrainer
from fastapi import Request, BackgroundTasks
from fastapi.responses import Response

import setting
from favicon_app.models import Favicon, favicon
from favicon_app.utils import header
from favicon_app.utils.file_util import FileUtil
from favicon_app.utils.filetype import helpers, filetype

urllib3.disable_warnings()
logging.captureWarnings(True)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# 获取当前所在目录的绝对路径
_current_dir = os.path.dirname(os.path.abspath(__file__))

_url_count = 0
_icon_count = 0
_cache_count = 0

# 预编译正则表达式，提高性能
pattern_icon = re.compile(r'(icon|shortcut icon|alternate icon|apple-touch-icon)+', re.I)
pattern_link = re.compile(r'(<link[^>]+rel=.(icon|shortcut icon|alternate icon|apple-touch-icon)[^>]+>)', re.I)


def _get_link_rel(links, entity: Favicon, _rel: str) -> Optional[str]:
    """从链接列表中查找指定rel类型的图标URL"""
    if not links:
        return None

    _result = None
    for link in links:
        r = link.get('rel')
        _r = ' '.join(r) if isinstance(r, list) else r
        _href = link.get('href')

        if _rel:
            if _r.lower() == _rel:
                _result = entity.get_icon_url(str(_href))
        else:
            _result = entity.get_icon_url(str(_href))

    return _result


def _parse_html(content: Optional[bytes], entity: Favicon) -> Optional[str]:
    """从HTML内容中解析图标URL"""
    if not content:
        return None

    try:
        # 尝试将bytes转换为字符串
        content_str = str(content).encode('utf-8', 'replace').decode('utf-8', 'replace')

        # 使用更高效的解析器
        bs = bs4.BeautifulSoup(content_str, features='lxml', parse_only=SoupStrainer("link"))
        if len(bs) == 0:
            bs = bs4.BeautifulSoup(content_str, features='html.parser', parse_only=SoupStrainer("link"))

        html_links = bs.find_all("link", rel=pattern_icon)

        # 处理<base>问题
        base_soup = bs4.BeautifulSoup(content_str, 'lxml', parse_only=SoupStrainer("base"))
        if base_soup:
            _base = base_soup.select_one('base[href]')
            if _base:
                logger.warning(f"-> 页面检测到<base>标签：{_base['href']} | {entity.domain} <-")

        # 如果没有找到，尝试使用正则表达式直接匹配
        if not html_links or len(html_links) == 0:
            content_links = pattern_link.findall(content_str)
            c_link = ''.join([_links[0] for _links in content_links])
            bs = bs4.BeautifulSoup(c_link, features='lxml')
            html_links = bs.find_all("link", rel=pattern_icon)

        if html_links and len(html_links) > 0:
            # 优先查找指定rel类型的图标
            icon_url = (_get_link_rel(html_links, entity, 'shortcut icon') or
                        _get_link_rel(html_links, entity, 'icon') or
                        _get_link_rel(html_links, entity, 'alternate icon') or
                        _get_link_rel(html_links, entity, ''))

            if icon_url:
                logger.debug(f"-> 从HTML获取图标URL: {icon_url}")

            return icon_url
    except Exception as e:
        logger.error(f"解析HTML失败: {e}")

    return None


def _get_file_md5(file_path: str) -> Optional[str]:
    """计算文件的MD5值"""
    try:
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            while True:
                buffer = f.read(1024 * 8)
                if not buffer:
                    break
                md5.update(buffer)
        return md5.hexdigest().lower()
    except Exception as e:
        logger.error(f"计算文件MD5失败 {file_path}: {e}")
        return None


default_icon_md5 = [
    _get_file_md5(setting.default_icon_path),
    '05231fb6b69aff47c3f35efe09c11ba0',
    '3ca64f83fdcf25135d87e08af65e68c9',
    'db470fd0b65c8c121477343c37f74f02',
    '52419f3f4f7d11945d272facc76c9e6a',
    'b8a0bf372c762e966cc99ede8682bc71',
    '71e9c45f29eadfa2ec5495302c22bcf6',
    'ababc687adac587b8a06e580ee79aaa1',
    '43802bddf65eeaab643adb8265bfbada',
    '669f77638e6c6eb274ed3ca36827cd72',
]


def _get_header(content_type: str, cache_time: int = None) -> dict:
    """生成响应头"""
    if cache_time is None:
        cache_time = setting.time_of_7_days

    _ct = 'image/x-icon'
    if content_type and content_type in header.image_type:
        _ct = content_type

    cache_control = 'no-store, no-cache, must-revalidate, max-age=0' if cache_time == 0 else f'public, max-age={cache_time}'

    return {
        'Content-Type': _ct,
        'Cache-Control': cache_control,
        'X-Robots-Tag': 'noindex, nofollow'
    }


def get_default(cache_time: int = None) -> Response:
    if cache_time is None:
        cache_time = setting.time_of_1_days
    return Response(content=setting.default_icon_file,
                    media_type="image/png",
                    headers=_get_header("image/png", cache_time))


def _is_default_icon_md5(icon_md5: str) -> bool:
    """检查图标MD5是否为默认图标"""
    return icon_md5 in default_icon_md5


def _is_default_icon_file(file_path: str) -> bool:
    """检查文件是否为默认图标"""
    if os.path.exists(file_path) and os.path.isfile(file_path):
        md5 = _get_file_md5(file_path)
        return md5 in default_icon_md5 if md5 else False
    return False


def _is_default_icon_byte(file_content: bytes) -> bool:
    """检查字节内容是否为默认图标"""
    try:
        md5 = hashlib.md5(file_content).hexdigest().lower()
        return md5 in default_icon_md5
    except Exception as e:
        logger.error(f"计算字节内容MD5失败: {e}")
        return False


def _get_cache_file(domain_md5: str, refresh: bool = False) -> Tuple[Optional[bytes], Optional[bytes]]:
    """从缓存中获取图标文件"""
    cache_path = os.path.join(setting.icon_root_path, 'data', 'icon', domain_md5[:2], f"{domain_md5}.png")
    if os.path.exists(cache_path) and os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0:
        try:
            cached_icon = FileUtil.read_file(cache_path, mode='rb')
            file_time = int(os.path.getmtime(cache_path))

            # 验证是否为有效的图片文件
            if not helpers.is_image(cached_icon):
                logger.warning(f"缓存的图标不是有效图片: {cache_path}")
                return None, None

            # 处理刷新请求或缓存过期情况
            if refresh:
                if int(time.time()) - file_time <= setting.time_of_12_hours:
                    logger.info(f"缓存文件修改时间在有效期内，不执行刷新: {cache_path}")
                    return cached_icon, cached_icon
                return cached_icon, None

            # 检查缓存是否过期（最大30天）
            if int(time.time()) - file_time > setting.time_of_30_days:
                logger.info(f"图标缓存过期(>30天): {cache_path}")
                return cached_icon, None

            # 默认图标，使用随机的缓存时间
            if (int(time.time()) - file_time > setting.time_of_1_days * random.randint(1, 7)
                    and _is_default_icon_file(cache_path)):
                logger.info(f"默认图标缓存过期: {cache_path}")
                return cached_icon, None

            return cached_icon, cached_icon
        except Exception as e:
            logger.error(f"读取缓存文件失败 {cache_path}: {e}")
            return None, None
    return None, None


def _get_cache_icon(domain_md5: str, refresh: bool = False) -> Tuple[Optional[bytes], Optional[bytes]]:
    """获取缓存的图标"""
    _cached, cached_icon = _get_cache_file(domain_md5, refresh)

    # 替换默认图标
    if _cached and _is_default_icon_byte(_cached):
        _cached = setting.default_icon_file
    if cached_icon and _is_default_icon_byte(cached_icon):
        cached_icon = setting.default_icon_file

    return _cached, cached_icon


async def get_favicon_handler(request: Request,
                              bg_tasks: BackgroundTasks,
                              url: Optional[str] = None,
                              refresh: Optional[str] = None) -> dict[str, str] | Response:
    """异步处理获取图标的请求"""
    global _url_count, _icon_count, _cache_count

    # 验证URL参数
    if not url:
        return {"message": "请提供url参数"}

    try:
        entity = Favicon(url)

        # 统计URL数量
        _url_count += 1

        # 验证域名
        if not entity.domain:
            logger.warning(f"无效的URL: {url}")
            return get_default(setting.time_of_1_days)

        # 检查缓存中的失败URL
        if favicon.is_failed_url(entity.domain):
            return get_default(setting.time_of_1_days)

        logger.debug(
            f"-> count (cached/icon/url): "f"{_cache_count}/{_icon_count}/{_url_count}"
        )

        # 检查缓存
        _cached, cached_icon = _get_cache_icon(entity.domain_md5, refresh=refresh in ['true', '1'])

        if _cached or cached_icon:
            # 使用缓存图标
            icon_content = cached_icon if cached_icon else _cached

            # 确定内容类型和缓存时间
            content_type = filetype.guess_mime(icon_content) if icon_content else ""
            cache_time = setting.time_of_12_hours \
                if _is_default_icon_byte(icon_content) else setting.time_of_7_days

            # 乐观缓存机制：检查缓存是否已过期但仍有缓存内容
            # _cached 存在但 cached_icon 为 None 表示缓存已过期
            if _cached and not cached_icon:
                # 缓存已过期，后台刷新缓存
                logger.info(f"缓存已过期，加入后台队列刷新(异步): {entity.domain}")
                bg_tasks.add_task(get_icon_async, entity, _cached)

            # 缓存计数
            _cache_count += 1
            return Response(content=icon_content,
                            media_type=content_type if content_type else "image/x-icon",
                            headers=_get_header(content_type, cache_time))
        else:
            # 没有缓存，开始图标处理，始终使用异步方法获取图标
            icon_content = await get_icon_async(entity, _cached)

            if not icon_content:
                # 获取失败，返回默认图标
                return get_default()

            # 确定内容类型和缓存时间
            content_type = filetype.guess_mime(icon_content) if icon_content else ""
            cache_time = setting.time_of_12_hours \
                if _is_default_icon_byte(icon_content) else setting.time_of_7_days

            return Response(content=icon_content,
                            media_type=content_type if content_type else "image/x-icon",
                            headers=_get_header(content_type, cache_time))
    except Exception as e:
        logger.error(f"处理图标请求时发生错误 {url}: {e}")
        # 返回默认图标
        return get_default()


async def get_icon_async(entity: Favicon, _cached: bytes = None) -> Optional[bytes]:
    """异步获取图标"""
    global _icon_count
    icon_content = None

    try:
        # 尝试从网站异步获取HTML内容
        html_content = await entity.req_get()
        if html_content:
            icon_url = _parse_html(html_content, entity)
        else:
            icon_url = None

        # 尝试不同的图标获取策略
        strategies = [
            # 0. 从原始网页标签链接中获取
            lambda: (icon_url, "原始网页标签") if icon_url else (None, None),
        ]

        # 2. 从配置文件加载其他图标获取接口
        for _template, _name in setting.FAVICON_APIS:
            strategies.append(
                lambda template=_template, name=_name:
                (template.format(domain=entity.domain, base_url=entity.get_base_url()), name)
            )

        for strategy in strategies:
            if icon_content:
                break

            strategy_url, strategy_name = strategy()
            if strategy_url is not None:
                logger.debug(f"-> 异步尝试从 {strategy_name} 获取图标")
                icon_content, icon_type = await entity.get_icon_file(strategy_url, strategy_url == '')

        # 图标获取失败，或图标不是支持的图片格式，写入默认图标
        if (not icon_content) or (not helpers.is_image(icon_content) or _is_default_icon_byte(icon_content)):
            logger.debug(f"-> 异步获取图标失败，使用默认图标: {entity.domain}")
            icon_content = _cached if _cached else setting.default_icon_file

        if icon_content:
            cache_path = os.path.join(setting.icon_root_path, 'data', 'icon', entity.domain_md5[:2], f"{entity.domain_md5}.png")
            md5_path = os.path.join(setting.icon_root_path, 'data', 'text', entity.domain_md5[:2], f"{entity.domain_md5}.txt")

            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                os.makedirs(os.path.dirname(md5_path), exist_ok=True)

                # 写入缓存文件（注意：文件IO操作仍然是同步的）
                FileUtil.write_file(cache_path, icon_content, mode='wb')
                FileUtil.write_file(md5_path, entity.domain)

                # 任务计数
                _icon_count += 1
            except Exception as e:
                logger.error(f"异步写入缓存文件失败: {e}")

        return icon_content
    except Exception as e:
        logger.error(f"异步获取图标时发生错误 {entity.domain}: {e}")
        return _cached or setting.default_icon_file
