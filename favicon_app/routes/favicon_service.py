# -*- coding: utf-8 -*-

import asyncio
import hashlib
import logging
import os
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

import bs4
from bs4 import SoupStrainer, XMLParsedAsHTMLWarning
from fastapi.responses import Response

import setting
from favicon_app.models import Favicon, favicon
from favicon_app.services import blacklist_service, stats_service
from favicon_app.utils import header
from favicon_app.utils.file_util import FileUtil
from favicon_app.utils.filetype import filetype, helpers

logger = logging.getLogger(__name__)

_blocked_svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<rect width="128" height="128" rx="16" fill="#fff"/>
<circle cx="64" cy="64" r="46" fill="#b42318"/>
<circle cx="64" cy="64" r="31" fill="none" stroke="#fff" stroke-width="10"/>
<path d="M42 86 86 42" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round"/>
</svg>'''


@dataclass
class CacheItem:
    content: bytes
    modified_at: float
    checked_at: float
    is_default: bool


@dataclass
class FetchResult:
    content: bytes
    refreshed: bool
    blocked: bool = False


_memory_cache: "OrderedDict[str, CacheItem]" = OrderedDict()
_memory_cache_bytes = 0
_fetch_tasks: dict[str, asyncio.Task] = {}
_direct_fetch_results: dict[str, asyncio.Future] = {}
_refresh_queue: Optional[asyncio.Queue] = None
_refresh_pending: set[str] = set()
_refresh_workers: list[asyncio.Task] = []


def _format_seconds(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _cache_path(cache_key: str) -> str:
    return os.path.join(setting.icon_root_path, 'data', 'icon', cache_key[:2], f'{cache_key}.png')


def _url_path(cache_key: str) -> str:
    return os.path.join(setting.icon_root_path, 'data', 'text', cache_key[:2], f'{cache_key}.txt')


def _legacy_cache_candidates(identity: str) -> list[tuple[str, Optional[str]]]:
    sha256_key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    candidates: list[tuple[str, Optional[str]]] = [
        (
            os.path.join(setting.icon_root_path, 'data', 'icon', sha256_key[:2], f'{sha256_key}.img'),
            None,
        ),
    ]
    try:
        domain = urlsplit(identity).hostname
        if domain:
            domain_key = hashlib.md5(
                domain.encode('utf-8'),
                usedforsecurity=False,
            ).hexdigest()
            candidates.extend([
                (
                    os.path.join(setting.icon_root_path, 'data', 'icon', domain_key[:2], f'{domain_key}.png'),
                    os.path.join(setting.icon_root_path, 'data', 'text', domain_key[:2], f'{domain_key}.txt'),
                ),
                (
                    os.path.join(setting.icon_root_path, 'data', 'icon', f'{domain_key}.png'),
                    os.path.join(setting.icon_root_path, 'data', 'text', f'{domain_key}.txt'),
                ),
            ])
    except (UnicodeError, ValueError):
        pass
    return candidates


def _is_file_expired(modified_at: float) -> bool:
    expire_time = setting.ICON_FILE_EXPIRE_TIME
    return expire_time >= 0 and time.time() - modified_at > expire_time


def _remove_cache_record(icon_path: str, url_path: Optional[str]) -> None:
    for path in (icon_path, url_path):
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning(
                '删除过期缓存失败：%s；%s；忽略',
                favicon._text_for_log(path),
                favicon._exception_for_log(exc),
            )


def _write_cache_record(cache_key: str, content: bytes, identity: str) -> bool:
    icon_path = _cache_path(cache_key)
    url_path = _url_path(cache_key)
    if not FileUtil.write_file(url_path, identity, atomic=True):
        logger.warning(
            '缓存映射写入失败：%s；保留旧文件，仅缓存内存',
            favicon._url_for_log(identity),
        )
        return False
    # The icon replacement is the commit point: new image data always has a mapping.
    return FileUtil.write_file(icon_path, content, mode='wb', atomic=True)


def _get_file_md5(file_path: str) -> Optional[str]:
    try:
        digest = hashlib.md5(usedforsecurity=False)
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(8192), b''):
                digest.update(chunk)
        return digest.hexdigest().lower()
    except OSError:
        return None


default_icon_md5 = {
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
    'c213d299a2638391440eff20c8cf0b8f',
}
default_icon_md5.discard(None)


def _is_default_icon(content: Optional[bytes]) -> bool:
    return bool(content) and hashlib.md5(
        content,
        usedforsecurity=False,
    ).hexdigest().lower() in default_icon_md5


def _get_header(content_type: str, cache_time: int, cache_status: str) -> dict[str, str]:
    media_type = content_type if content_type in header.image_type else 'image/x-icon'
    cache_control = (
        'no-store, no-cache, must-revalidate, max-age=0'
        if cache_time == 0
        else f'public, max-age={cache_time}, stale-while-revalidate={setting.ICON_REFRESH_INTERVAL}'
    )
    return {
        'Content-Type': media_type,
        'Cache-Control': cache_control,
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': 'X-Favicon-Cache',
        'X-Robots-Tag': 'noindex, nofollow',
        'X-Favicon-Cache': cache_status,
    }


def _image_response(
        content: bytes,
        cache_status: str,
        default: bool = False,
        cache_time: Optional[int] = None,
) -> Response:
    content_type = filetype.guess_mime(content) or 'image/x-icon'
    effective_cache_time = cache_time
    if effective_cache_time is None:
        effective_cache_time = setting.DEFAULT_CLIENT_CACHE_TIME if default else setting.ICON_CLIENT_CACHE_TIME
    return Response(
        content=content,
        media_type=content_type,
        headers=_get_header(content_type, effective_cache_time, cache_status),
    )


def get_default(cache_time: Optional[int] = None, cache_status: str = 'FALLBACK') -> Response:
    effective_cache_time = setting.DEFAULT_CLIENT_CACHE_TIME if cache_time is None else cache_time
    return Response(
        content=setting.default_icon_file,
        media_type='image/png',
        headers=_get_header('image/png', effective_cache_time, cache_status),
    )


def get_blocked() -> Response:
    if setting.URL_BLACKLIST_RESPONSE == 'default':
        return get_default(cache_time=0, cache_status='BLOCKED')
    return Response(
        content=_blocked_svg,
        media_type='image/svg+xml',
        headers=_get_header('image/svg+xml', 0, 'BLOCKED'),
    )


def _read_cache_file(
        cache_key: str,
        identity: Optional[str] = None,
) -> Optional[CacheItem]:
    current_path = _cache_path(cache_key)
    current_url_path = _url_path(cache_key)
    candidates = [(current_path, current_url_path)]
    if identity:
        candidates.extend(_legacy_cache_candidates(identity))

    for path, mapping_path in candidates:
        try:
            if not os.path.isfile(path):
                continue
            modified_at = os.path.getmtime(path)
            if _is_file_expired(modified_at):
                _remove_cache_record(path, mapping_path)
                continue
            if os.path.getsize(path) <= 0 or os.path.getsize(path) > setting.MAX_ICON_BYTES:
                continue

            if identity and mapping_path and os.path.isfile(mapping_path):
                mapped = (FileUtil.read_file(mapping_path, mode='r') or '').strip()
                domain = urlsplit(identity).hostname or ''
                if mapped and mapped not in (identity, domain):
                    logger.warning(
                        '缓存冲突：%s；忽略冲突文件',
                        favicon._url_for_log(identity),
                    )
                    continue

            content = FileUtil.read_file(path, mode='rb', max_size=setting.MAX_ICON_BYTES)
            if not content or not helpers.is_image(content):
                continue

            if identity and (path != current_path or not os.path.isfile(current_url_path)):
                if _write_cache_record(cache_key, content, identity):
                    try:
                        os.utime(current_path, (modified_at, modified_at))
                    except OSError:
                        pass
                    if path != current_path:
                        _remove_cache_record(path, mapping_path)

            is_default = _is_default_icon(content)
            return CacheItem(
                content=setting.default_icon_file if is_default else content,
                modified_at=modified_at,
                checked_at=time.time(),
                is_default=is_default,
            )
        except OSError as exc:
            logger.warning(
                '缓存读取失败：%s；%s；忽略并重新抓取',
                favicon._url_for_log(identity or '未知'),
                favicon._exception_for_log(exc),
            )
    return None


async def _get_cached(cache_key: str, identity: Optional[str] = None) -> Optional[CacheItem]:
    now = time.time()
    item = _memory_cache.get(cache_key)
    if item and _is_file_expired(item.modified_at):
        _memory_remove(cache_key)
        await asyncio.to_thread(_remove_cache_record, _cache_path(cache_key), _url_path(cache_key))
        item = None
    if item and now - item.checked_at < setting.MEMORY_CACHE_RECHECK_INTERVAL:
        _memory_cache.move_to_end(cache_key)
        return item

    item = await asyncio.to_thread(_read_cache_file, cache_key, identity)
    if item:
        _memory_put(cache_key, item)
    else:
        _memory_remove(cache_key)
    return item


def _memory_remove(cache_key: str) -> None:
    global _memory_cache_bytes
    previous = _memory_cache.pop(cache_key, None)
    if previous:
        _memory_cache_bytes -= len(previous.content)


def _memory_put(cache_key: str, item: CacheItem) -> None:
    global _memory_cache_bytes
    _memory_remove(cache_key)
    if len(item.content) > setting.MEMORY_CACHE_ITEM_MAX_BYTES:
        return
    _memory_cache[cache_key] = item
    _memory_cache_bytes += len(item.content)
    _memory_cache.move_to_end(cache_key)
    while (_memory_cache and (
            len(_memory_cache) > setting.MEMORY_CACHE_MAX_ITEMS
            or _memory_cache_bytes > setting.MEMORY_CACHE_MAX_BYTES)):
        _, removed = _memory_cache.popitem(last=False)
        _memory_cache_bytes -= len(removed.content)


async def _store_cache(entity: Favicon, content: bytes) -> bool:
    if not entity.domain_md5 or not entity.cache_identity:
        return False
    persisted = await asyncio.to_thread(
            _write_cache_record,
            entity.domain_md5,
            content,
            entity.cache_identity,
    )
    now = time.time()
    _memory_put(entity.domain_md5, CacheItem(
        content=content,
        modified_at=now,
        checked_at=now,
        is_default=False,
    ))
    if not persisted:
        logger.warning(
            '磁盘缓存失败：%s；仅使用内存缓存',
            favicon._url_for_log(entity.cache_identity),
        )
    return persisted


def _parse_html_icons(content: Optional[bytes], entity: Favicon) -> list[str]:
    if not content or not entity.page_url:
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
            soup = bs4.BeautifulSoup(
                content,
                features='lxml',
                parse_only=SoupStrainer(['base', 'link']),
            )
        base_url = entity.page_url
        base = soup.find('base', href=True)
        if base:
            base_url = urljoin(base_url, base.get('href'))

        candidates = []
        for link in soup.find_all('link', href=True):
            rel = {str(value).lower() for value in (link.get('rel') or [])}
            if not rel.intersection({'icon', 'apple-touch-icon'}):
                continue
            priority = 0 if 'icon' in rel else 1
            candidates.append((priority, link.get('href')))

        icon_urls = []
        for _, href in sorted(candidates, key=lambda item: item[0]):
            icon_url = entity.get_icon_url(urljoin(base_url, href))
            if icon_url and icon_url not in icon_urls:
                icon_urls.append(icon_url)
        return icon_urls
    except Exception as exc:
        logger.warning(
            'HTML解析失败：%s；%s；尝试/favicon.ico',
            favicon._url_for_log(entity.page_url),
            favicon._exception_for_log(exc),
        )
    return []


def _parse_html(content: Optional[bytes], entity: Favicon) -> Optional[str]:
    """Compatibility helper returning the highest-priority HTML icon."""
    icons = _parse_html_icons(content, entity)
    return icons[0] if icons else None


async def _try_icon_candidates(
        entity: Favicon,
        candidates: list[tuple[str, str, bool]],
        deadline: float,
        timeout_limit: float,
) -> Optional[bytes]:
    loop = asyncio.get_running_loop()
    for index, (strategy_url, strategy_name, use_default) in enumerate(candidates):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        if use_default:
            candidate_url = urljoin((entity.get_base_url() or '') + '/', 'favicon.ico')
        elif strategy_url.lower().startswith('data:image'):
            candidate_url = favicon._url_for_log(strategy_url)
        else:
            candidate_url = strategy_url
        has_next = index + 1 < len(candidates)
        next_action = '下一候选' if has_next else '结束当前阶段'
        source = favicon._text_for_log(strategy_name, 40)
        logger.debug(
            '尝试候选：%s；%s',
            favicon._url_for_log(candidate_url),
            source,
        )
        request_timeout = min(max(0.1, timeout_limit), remaining)
        try:
            async with asyncio.timeout(request_timeout):
                content, _ = await entity.get_icon_file(
                    strategy_url,
                    use_default,
                    retries=0,
                    timeout=request_timeout,
                )
        except asyncio.TimeoutError:
            logger.warning(
                '候选超时：%s；%s；限制%ss；%s',
                favicon._url_for_log(candidate_url),
                source,
                _format_seconds(request_timeout),
                next_action,
            )
            continue
        if entity.icon_too_large:
            logger.warning(
                '候选过大：%s；%s；上限=%d；%s',
                favicon._url_for_log(candidate_url),
                source,
                setting.MAX_ICON_BYTES,
                next_action,
            )
            continue
        if not content or len(content) > setting.MAX_ICON_BYTES:
            logger.debug(
                '候选无效：%s；%s；%s',
                favicon._url_for_log(candidate_url),
                source,
                next_action,
            )
            continue
        if not helpers.is_image(content) or _is_default_icon(content):
            logger.debug(
                '候选忽略：%s；%s；无效或占位图；%s',
                favicon._url_for_log(candidate_url),
                source,
                next_action,
            )
            continue
        logger.debug(
            '候选成功：%s；%s；写入缓存',
            favicon._url_for_log(candidate_url),
            source,
        )
        return content
    return None


async def _fetch_direct_icon(entity: Favicon, deadline: float) -> Optional[bytes]:
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    if remaining <= 0:
        return None
    html_content = await entity.req_get(retries=0, timeout=remaining)
    html_icon_urls = await asyncio.to_thread(_parse_html_icons, html_content, entity)
    candidates: list[tuple[str, str, bool]] = [
        (icon_url, '站点 HTML 图标声明', False)
        for icon_url in html_icon_urls
    ]
    candidates.append(('', '站点默认 /favicon.ico', True))
    return await _try_icon_candidates(
        entity,
        candidates,
        deadline,
        setting.DIRECT_FETCH_TIMEOUT,
    )


async def _fetch_fallback_icon(entity: Favicon, deadline: float) -> Optional[bytes]:
    candidates = [
        (
            template.format(domain=entity.domain, base_url=entity.get_base_url()),
            name,
            False,
        )
        for template, name in setting.FAVICON_APIS
        if template
    ]
    return await _try_icon_candidates(
        entity,
        candidates,
        deadline,
        setting.FALLBACK_FETCH_TIMEOUT,
    )


async def get_icon_async(
        entity: Favicon,
        stale_content: Optional[bytes] = None,
        direct_result: Optional[asyncio.Future] = None,
) -> FetchResult:
    """Try the origin first, then continue provider fallbacks after signaling the caller."""
    fallback_content = stale_content or setting.default_icon_file
    if not entity.domain_md5 or not entity.cache_identity:
        result = FetchResult(fallback_content, False)
        if direct_result is not None and not direct_result.done():
            direct_result.set_result(result)
        return result

    if await blacklist_service.is_blocked(entity.cache_identity):
        result = FetchResult(fallback_content, False, blocked=True)
        if direct_result is not None and not direct_result.done():
            direct_result.set_result(result)
        return result

    try:
        loop = asyncio.get_running_loop()
        overall_deadline = loop.time() + max(0.1, setting.FETCH_TOTAL_TIMEOUT)
        direct_timeout = min(
            max(0.1, setting.DIRECT_FETCH_TIMEOUT),
            max(0.1, overall_deadline - loop.time()),
        )
        direct_deadline = loop.time() + direct_timeout
        direct_failure_reason: Optional[str] = None
        try:
            async with asyncio.timeout(direct_timeout):
                content = await _fetch_direct_icon(entity, direct_deadline)
        except asyncio.TimeoutError:
            direct_failure_reason = f'超过{_format_seconds(direct_timeout)}s'
            content = None
        except Exception as exc:
            direct_failure_reason = favicon._exception_for_log(exc)
            content = None
        if content and await blacklist_service.is_blocked(entity.cache_identity):
            result = FetchResult(fallback_content, False, blocked=True)
            if direct_result is not None and not direct_result.done():
                direct_result.set_result(result)
            return result
        if content:
            await _store_cache(entity, content)
            await asyncio.to_thread(favicon.clear_failed_url, entity.cache_identity)
            logger.info(
                '直连成功：%s；已更新缓存',
                favicon._url_for_log(entity.cache_identity),
            )
            result = FetchResult(content, True)
            if direct_result is not None and not direct_result.done():
                direct_result.set_result(result)
            return result

        if direct_failure_reason is None:
            direct_failure_reason = '未获取到有效图标'
        configured_fallbacks = sum(1 for template, _ in setting.FAVICON_APIS if template)
        if configured_fallbacks:
            if direct_result is not None:
                direct_next = f'先返回旧图，后台尝试{configured_fallbacks}个三方源'
            else:
                direct_next = f'尝试{configured_fallbacks}个三方源'
        else:
            direct_next = '写入负缓存'
        logger.warning(
            '直连失败：%s；%s；%s',
            favicon._url_for_log(entity.cache_identity),
            direct_failure_reason,
            direct_next,
        )

        direct_failure = FetchResult(fallback_content, False)
        if await blacklist_service.is_blocked(entity.cache_identity):
            blocked_result = FetchResult(fallback_content, False, blocked=True)
            if direct_result is not None and not direct_result.done():
                direct_result.set_result(blocked_result)
            return blocked_result
        if direct_result is not None and not direct_result.done():
            direct_result.set_result(direct_failure)

        content = await _fetch_fallback_icon(entity, overall_deadline)
        if await blacklist_service.is_blocked(entity.cache_identity):
            return FetchResult(fallback_content, False, blocked=True)
        if content:
            await _store_cache(entity, content)
            await asyncio.to_thread(favicon.clear_failed_url, entity.cache_identity)
            logger.info(
                '第三方成功：%s；已更新缓存',
                favicon._url_for_log(entity.cache_identity),
            )
            return FetchResult(content, True)

        negative_ttl = await asyncio.to_thread(favicon.add_failed_url, entity.cache_identity)
        retained = '保留旧图' if stale_content else '使用默认图'
        if negative_ttl > 0:
            failure_action = f'负缓存{negative_ttl}秒，{retained}'
        else:
            failure_action = f'{retained}，后续可重试'
        logger.warning(
            '全部来源失败：%s；无有效图标；%s',
            favicon._url_for_log(entity.cache_identity),
            failure_action,
        )
        return direct_failure
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if await blacklist_service.is_blocked(entity.cache_identity):
            blocked_result = FetchResult(fallback_content, False, blocked=True)
            if direct_result is not None and not direct_result.done():
                direct_result.set_result(blocked_result)
            return blocked_result
        failure = FetchResult(fallback_content, False)
        if direct_result is not None and not direct_result.done():
            direct_result.set_result(failure)
        negative_ttl = await asyncio.to_thread(favicon.add_failed_url, entity.cache_identity)
        retained = '保留旧图' if stale_content else '使用默认图'
        negative_action = (
            f'负缓存{negative_ttl}秒，{retained}'
            if negative_ttl > 0
            else retained
        )
        logger.warning(
            '抓取异常：%s；%s；%s',
            favicon._url_for_log(entity.cache_identity),
            favicon._exception_for_log(exc),
            negative_action,
        )
        return failure


def _fetch_done(cache_key: str, identity: str, task: asyncio.Task) -> None:
    if _fetch_tasks.get(cache_key) is task:
        _fetch_tasks.pop(cache_key, None)
    direct_result = _direct_fetch_results.pop(cache_key, None)
    if direct_result is not None and not direct_result.done():
        direct_result.cancel()
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(
            '后台抓取异常：%s；%s；移除任务',
            favicon._url_for_log(identity),
            favicon._exception_for_log(exc),
        )


def _get_or_create_fetch(entity: Favicon, stale_content: Optional[bytes]) -> Optional[asyncio.Task]:
    cache_key = entity.domain_md5
    if not cache_key:
        return None
    existing = _fetch_tasks.get(cache_key)
    if existing:
        return existing
    if len(_fetch_tasks) >= setting.MAX_INFLIGHT_FETCHES:
        logger.warning(
            '抓取容量已满：%s；并发%d/%d；返回旧图',
            favicon._url_for_log(entity.cache_identity),
            len(_fetch_tasks),
            setting.MAX_INFLIGHT_FETCHES,
        )
        return None
    direct_result = asyncio.get_running_loop().create_future()

    async def run_fetch() -> FetchResult:
        result = await get_icon_async(entity, stale_content, direct_result)
        if not direct_result.done():
            direct_result.set_result(result)
        return result

    task = asyncio.create_task(run_fetch())
    _fetch_tasks[cache_key] = task
    _direct_fetch_results[cache_key] = direct_result
    task.add_done_callback(
        lambda finished: _fetch_done(cache_key, entity.cache_identity or '未知', finished)
    )
    return task


async def _refresh_worker() -> None:
    queue = _refresh_queue
    if queue is None:
        raise RuntimeError('后台刷新队列尚未初始化')
    while True:
        entity = await queue.get()
        try:
            blocked = await blacklist_service.is_blocked(entity.cache_identity)
            task = None if blocked else _get_or_create_fetch(entity, None)
            if task:
                await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                '后台刷新异常：%s；%s；继续下一项',
                favicon._url_for_log(entity.cache_identity),
                favicon._exception_for_log(exc),
            )
        finally:
            if entity.domain_md5:
                _refresh_pending.discard(entity.domain_md5)
            queue.task_done()


async def start_refresh_workers() -> None:
    global _refresh_queue
    if _refresh_queue is not None:
        return
    _refresh_queue = asyncio.Queue(maxsize=setting.REFRESH_QUEUE_MAX_SIZE)
    for _ in range(setting.REFRESH_WORKERS):
        _refresh_workers.append(asyncio.create_task(_refresh_worker()))


async def stop_refresh_workers() -> None:
    global _refresh_queue, _memory_cache_bytes
    workers = list(_refresh_workers)
    _refresh_workers.clear()
    for task in workers:
        task.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)

    fetches = list(_fetch_tasks.values())
    for task in fetches:
        task.cancel()
    if fetches:
        await asyncio.gather(*fetches, return_exceptions=True)
    _fetch_tasks.clear()
    for direct_result in _direct_fetch_results.values():
        if not direct_result.done():
            direct_result.cancel()
    _direct_fetch_results.clear()
    _refresh_pending.clear()
    _memory_cache.clear()
    _memory_cache_bytes = 0
    _refresh_queue = None


def enqueue_refresh(entity: Favicon) -> bool:
    if _refresh_queue is None or not entity.domain_md5:
        return False
    if entity.domain_md5 in _refresh_pending or entity.domain_md5 in _fetch_tasks:
        return True
    try:
        _refresh_queue.put_nowait(entity)
        _refresh_pending.add(entity.domain_md5)
        return True
    except asyncio.QueueFull:
        logger.warning(
            '刷新队列已满：%s；上限=%d；返回旧图',
            favicon._url_for_log(entity.cache_identity),
            setting.REFRESH_QUEUE_MAX_SIZE,
        )
        return False


async def get_favicon_handler(
        url: Optional[str] = None,
        refresh: Optional[str] = None,
        track: bool = False,
        source: Optional[str] = None,
) -> Response:
    entity = Favicon(url or '')
    if not entity.domain_md5 or not entity.cache_identity:
        return get_default(cache_status='INVALID')
    if await blacklist_service.is_blocked(entity.cache_identity):
        logger.info(
            '网址黑名单命中：%s；返回禁止访问图标',
            favicon._url_for_log(entity.cache_identity),
        )
        return get_blocked()
    if track:
        try:
            stats_service.record_request(entity.cache_identity, source)
        except Exception as exc:
            logger.exception(
                '统计记录异常：%s；%s；继续处理图标',
                favicon._url_for_log(entity.cache_identity),
                favicon._exception_for_log(exc),
            )

    force_refresh = (refresh or '').strip().lower() in ('true', '1')
    cached: Optional[CacheItem] = None
    try:
        async with asyncio.timeout(max(0.1, setting.FOREGROUND_RESPONSE_TIMEOUT)):
            cached = await _get_cached(entity.domain_md5, entity.cache_identity)
            if await blacklist_service.is_blocked(entity.cache_identity):
                return get_blocked()
            if cached and not force_refresh:
                age = max(0, time.time() - cached.modified_at)
                is_default = cached.is_default
                needs_refresh = is_default or age >= setting.ICON_REFRESH_INTERVAL
                refresh_active = entity.domain_md5 in _refresh_pending or entity.domain_md5 in _fetch_tasks
                negative_ttl = 0
                if needs_refresh and not refresh_active:
                    negative_ttl = await asyncio.to_thread(
                        favicon.failed_url_ttl,
                        entity.cache_identity,
                    )
                    if negative_ttl <= 0:
                        enqueue_refresh(entity)
                status = 'STALE' if needs_refresh else 'HIT'
                response_cache_time = (
                    negative_ttl
                    if negative_ttl > 0
                    else (0 if needs_refresh else None)
                )
                return _image_response(
                    cached.content,
                    status,
                    default=is_default,
                    cache_time=response_cache_time,
                )

            if not force_refresh:
                negative_ttl = await asyncio.to_thread(favicon.failed_url_ttl, entity.cache_identity)
                if negative_ttl > 0:
                    return get_default(cache_time=negative_ttl, cache_status='NEGATIVE')

            task = _get_or_create_fetch(entity, cached.content if cached else None)
            if not task:
                if cached:
                    return _image_response(cached.content, 'BUSY', default=cached.is_default, cache_time=0)
                return get_default(cache_time=0, cache_status='BUSY')
            direct_result = _direct_fetch_results.get(entity.domain_md5)
            wait_target = direct_result if direct_result is not None else task
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(wait_target),
                    timeout=setting.FOREGROUND_FETCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    '前台超时：%s；限制%ss；返回旧图，后台继续',
                    favicon._url_for_log(entity.cache_identity),
                    _format_seconds(setting.FOREGROUND_FETCH_TIMEOUT),
                )
                if await blacklist_service.is_blocked(entity.cache_identity):
                    return get_blocked()
                if cached:
                    return _image_response(cached.content, 'PROCESSING', default=cached.is_default, cache_time=0)
                return get_default(cache_time=0, cache_status='PROCESSING')

            content = result.content
            if result.blocked:
                return get_blocked()
            if not result.refreshed or not content or _is_default_icon(content):
                if cached:
                    return _image_response(cached.content, 'STALE', default=cached.is_default, cache_time=0)
                return get_default(cache_time=0, cache_status='PROCESSING')
            return _image_response(content, 'REFRESHED' if force_refresh else 'MISS')
    except asyncio.TimeoutError:
        if await blacklist_service.is_blocked(entity.cache_identity):
            return get_blocked()
        queued = enqueue_refresh(entity)
        follow_up = (
            '返回旧图，后台继续'
            if queued
            else '返回旧图，后续可重试'
        )
        logger.warning(
            '接口超时：%s；限制%ss；%s',
            favicon._url_for_log(entity.cache_identity),
            _format_seconds(setting.FOREGROUND_RESPONSE_TIMEOUT),
            follow_up,
        )
        if cached:
            return _image_response(cached.content, 'PROCESSING', default=cached.is_default, cache_time=0)
        return get_default(cache_time=0, cache_status='PROCESSING')
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if await blacklist_service.is_blocked(entity.cache_identity):
            return get_blocked()
        fallback_cached = cached
        if fallback_cached is None:
            memory_item = _memory_cache.get(entity.domain_md5)
            if memory_item and not _is_file_expired(memory_item.modified_at):
                fallback_cached = memory_item
        logger.exception(
            '接口异常：%s；%s；%s',
            favicon._url_for_log(entity.cache_identity),
            favicon._exception_for_log(exc),
            '返回旧图' if fallback_cached else '返回默认图',
        )
        if fallback_cached:
            return _image_response(
                fallback_cached.content,
                'STALE',
                default=fallback_cached.is_default,
                cache_time=0,
            )
        return get_default(cache_time=0, cache_status='FALLBACK')
