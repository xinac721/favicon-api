# -*- coding: utf-8 -*-

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
from collections import OrderedDict
from typing import Optional, Tuple
from urllib.parse import unquote_to_bytes, urljoin, urlsplit, urlunsplit
from urllib.request import getproxies

import aiohttp
from aiohttp.abc import AbstractResolver

import setting
from favicon_app.services import blacklist_service
from favicon_app.utils import header
from favicon_app.utils.file_util import FileUtil
from favicon_app.utils.filetype import filetype, helpers

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = setting.HTTP_TOTAL_TIMEOUT
DEFAULT_RETRIES = 1
_aiohttp_client: Optional[aiohttp.ClientSession] = None
_public_resolver: Optional["PublicResolver"] = None
_request_semaphore: Optional[asyncio.Semaphore] = None
_negative_memory_cache: "OrderedDict[str, float]" = OrderedDict()
_negative_failure_counts: "OrderedDict[str, int]" = OrderedDict()
_negative_memory_lock = threading.Lock()

_domain_label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
_percent_encoded_url_prefix = re.compile(
    r'(?i)^(?:https?%3a%2f%2f|[^/?#%\s]+(?:%3a\d+)?%2f)'
)
_redirect_statuses = {301, 302, 303, 307, 308}


class ResponseTooLargeError(Exception):
    pass


def _is_usable_unicast_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return (
            not address.is_multicast
            and not address.is_unspecified
            and (not address.is_reserved or address.is_loopback)
        )
    except ValueError:
        return False


def _is_public_ip(value: str) -> bool:
    try:
        return _is_usable_unicast_ip(value) and ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _is_allowed_target_ip(value: str) -> bool:
    return _is_usable_unicast_ip(value) and (
        setting.ALLOW_PRIVATE_NETWORK or _is_public_ip(value)
    )


def _text_for_log(value: object, max_length: int = 120) -> str:
    text = str(value).strip().replace('\r', r'\r').replace('\n', r'\n')
    text = re.sub(r'(?i)(://)([^/@\s]+)@', r'\1***@', text)
    if len(text) <= max_length:
        return text
    return f'{text[:max(0, max_length - 3)]}...'


def _url_for_log(url: object) -> str:
    """Return a bounded, single-line URL representation suitable for logs."""
    if not isinstance(url, str):
        return _text_for_log(repr(url), 200)
    value = url.strip()
    if _percent_encoded_url_prefix.match(value):
        value = unquote_to_bytes(value).decode('utf-8', errors='replace').strip()
    if value.lower().startswith('data:image'):
        return f'data:image 内嵌数据（长度={len(value)}）'
    return _text_for_log(value, 200)


def _exception_for_log(exc: BaseException) -> str:
    detail = _text_for_log(exc, 120)
    return f'{type(exc).__name__}: {detail}' if detail else type(exc).__name__


def _map_custom_protocol(url: object) -> object:
    """Map configured custom protocols only for the top-level API target."""
    if not isinstance(url, str):
        return url
    value = url.strip()
    protocol_match = re.match(r'(?i)^([a-z][a-z\d+.-]*):\/\/', value)
    if not protocol_match:
        return url
    mapped_origin = setting.CUSTOM_PROTOCOL_MAPPINGS.get(protocol_match.group(1).lower())
    if isinstance(mapped_origin, str) and mapped_origin.strip():
        return mapped_origin.strip()
    return url


def _normalize_url_with_reason(url: object) -> tuple[Optional[str], Optional[str]]:
    """Normalize an HTTP URL and return a Chinese rejection reason on failure."""
    if not isinstance(url, str):
        return None, '网址类型不是字符串'

    value = url.strip()
    if not value:
        return None, '网址为空'
    if _percent_encoded_url_prefix.match(value):
        try:
            value = unquote_to_bytes(value).decode('utf-8').strip()
        except UnicodeDecodeError:
            return None, '百分号编码的网址不是有效的 UTF-8 文本'
    if value.startswith('//'):
        value = 'http:' + value
    elif '://' not in value:
        value = 'http://' + value

    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https'):
            scheme = _text_for_log(parsed.scheme or '未知', 32)
            return None, f'不支持 {scheme} 协议，仅允许 HTTP 或 HTTPS'
        if parsed.username or parsed.password:
            return None, '网址包含用户名或密码'
        if not parsed.hostname:
            return None, '网址缺少主机名'

        host = parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        try:
            port = parsed.port
        except ValueError:
            return None, '端口格式无效或超出 1-65535 范围'

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253:
                return None, '域名长度超过 253 个字符'
            if '.' not in host and not setting.ALLOW_PRIVATE_NETWORK:
                return None, '单标签主机名或内网域名默认禁止访问'
            if any(not _domain_label.fullmatch(label) for label in host.split('.')):
                return None, '域名格式无效'
        else:
            if not _is_allowed_target_ip(host):
                return None, '目标 IP 不是有效的公网地址'

        display_host = f'[{host}]' if ':' in host else host
        netloc = f'{display_host}:{port}' if port is not None else display_host
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or '/', parsed.query, '')), None
    except UnicodeError:
        return None, '国际化域名编码无效'
    except ValueError as exc:
        return None, f'网址结构无效（{_text_for_log(exc, 80)}）'


def _normalize_url(url: str) -> Optional[str]:
    """Normalize an HTTP URL without performing DNS resolution."""
    normalized, _ = _normalize_url_with_reason(url)
    return normalized


class PublicResolver(AbstractResolver):
    """Cache and coalesce DNS lookups while rejecting non-public answers."""

    def __init__(
            self,
            trusted_proxy_hosts: Optional[set[str]] = None,
            cache_ttl: float = 60.0,
            cache_max_items: int = 10000,
    ):
        self._resolver = aiohttp.DefaultResolver()
        self._trusted_proxy_hosts = {
            host.rstrip('.').lower()
            for host in (trusted_proxy_hosts or set())
        }
        self._cache_ttl = max(0.0, cache_ttl)
        self._cache_max_items = max(0, cache_max_items)
        self._cache: "OrderedDict[tuple[str, int, int], tuple[float, list[dict]]]" = (
            OrderedDict()
        )
        self._inflight: dict[
            tuple[str, int, int],
            set[asyncio.Future],
        ] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        return await self._resolve_checked(
            host,
            port,
            family,
            allow_trusted_proxy=True,
        )

    async def resolve_public(self, host: str, port: int = 0, family: int = socket.AF_INET):
        return await self._resolve_checked(
            host,
            port,
            family,
            allow_trusted_proxy=False,
        )

    async def _resolve_checked(
            self,
            host: str,
            port: int,
            family: int,
            allow_trusted_proxy: bool,
    ):
        results = await self._resolve_cached(host, port, family)
        if not results:
            raise OSError(f'域名 {host} 没有可用的 DNS 解析结果')

        trusted_proxy = (
            allow_trusted_proxy
            and host.rstrip('.').lower() in self._trusted_proxy_hosts
        )
        invalid = [
            item['host'] for item in results
            if not (
                _is_usable_unicast_ip(item['host'])
                if trusted_proxy
                else _is_allowed_target_ip(item['host'])
            )
        ]
        if invalid:
            raise OSError(f'域名 {host} 解析到禁止访问的非公网地址 {invalid[0]}')
        return results

    async def _resolve_cached(self, host: str, port: int, family: int) -> list[dict]:
        if self._closed:
            raise OSError('DNS 解析器已经关闭')

        loop = asyncio.get_running_loop()
        key = (host.rstrip('.').lower(), port, family)
        cached = self._cache.get(key)
        if cached:
            expires_at, results = cached
            if expires_at > loop.time():
                self._cache.move_to_end(key)
                return [dict(item) for item in results]
            self._cache.pop(key, None)

        waiter = loop.create_future()
        waiters = self._inflight.get(key)
        if waiters is None:
            waiters = set()
            self._inflight[key] = waiters
            waiters.add(waiter)
            task = asyncio.create_task(
                self._resolve_and_publish(key, host, port, family),
                name=f'dns-resolve:{host}',
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            waiters.add(waiter)

        try:
            results, error = await waiter
        finally:
            waiters.discard(waiter)
        if error is not None:
            raise error
        return [dict(item) for item in results]

    async def _resolve_and_publish(
            self,
            key: tuple[str, int, int],
            host: str,
            port: int,
            family: int,
    ) -> None:
        results: list[dict] = []
        error: Optional[Exception] = None
        cancelled = False
        try:
            results = await self._resolver.resolve(host, port, family)
            if self._cache_ttl > 0 and self._cache_max_items > 0:
                self._cache[key] = (
                    asyncio.get_running_loop().time() + self._cache_ttl,
                    [dict(item) for item in results],
                )
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_max_items:
                    self._cache.popitem(last=False)
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:
            error = exc

        waiters = self._inflight.pop(key, set())
        active_waiters = [waiter for waiter in waiters if not waiter.done()]
        if error is not None:
            display_host = f'[{host}]' if ':' in host else host
            target = f'{display_host}:{port}' if port else display_host
            follow_up = (
                '通知等待请求，继续后续来源'
                if active_waiters
                else '原请求已超时，结束解析'
            )
            logger.warning(
                'DNS失败：%s；%s；%s',
                _url_for_log(target),
                _describe_dns_error(error),
                follow_up,
            )

        for waiter in active_waiters:
            if cancelled:
                waiter.cancel()
            else:
                # Publish failures as values so a concurrently cancelled waiter
                # can never leave an unconsumed Future exception behind.
                waiter.set_result((results, error))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for waiters in self._inflight.values():
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
        self._inflight.clear()
        self._cache.clear()
        await self._resolver.close()


def _describe_dns_error(exc: Exception) -> str:
    if isinstance(exc, socket.gaierror):
        error_code = exc.errno
        if error_code == socket.EAI_AGAIN:
            return f'DNS 服务暂时不可用（错误码 {error_code}）'
        if error_code == socket.EAI_NONAME:
            return f'域名不存在或没有可用解析记录（错误码 {error_code}）'
        if error_code == socket.EAI_FAIL:
            return f'DNS 服务返回不可恢复错误（错误码 {error_code}）'
        return f'DNS 解析错误（错误码 {error_code}）'
    error_code = getattr(exc, 'errno', None)
    return f'系统 DNS 解析异常（类型 {type(exc).__name__}，错误码 {error_code}）'


async def initialize_http_client() -> None:
    global _aiohttp_client, _public_resolver, _request_semaphore
    if _aiohttp_client is not None and not _aiohttp_client.closed:
        return

    proxy_hosts = set()
    if setting.HTTP_TRUST_ENV:
        for proxy_url in getproxies().values():
            try:
                proxy_host = urlsplit(proxy_url).hostname
            except (TypeError, ValueError):
                proxy_host = None
            if proxy_host:
                proxy_hosts.add(proxy_host)
    _public_resolver = PublicResolver(proxy_hosts)
    connector = aiohttp.TCPConnector(
        ssl=False,
        resolver=_public_resolver,
        limit=setting.HTTP_CONNECTION_LIMIT,
        limit_per_host=setting.HTTP_CONNECTION_LIMIT_PER_HOST,
        # PublicResolver owns the bounded cache and avoids Python 3.14's
        # "exception in shielded future" path in aiohttp's DNS cache.
        use_dns_cache=False,
    )
    timeout = aiohttp.ClientTimeout(
        total=setting.HTTP_TOTAL_TIMEOUT,
        connect=setting.HTTP_CONNECT_TIMEOUT,
    )
    _aiohttp_client = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        raise_for_status=False,
        trust_env=setting.HTTP_TRUST_ENV,
    )
    _request_semaphore = asyncio.Semaphore(setting.HTTP_MAX_CONCURRENCY)


async def close_http_client() -> None:
    global _aiohttp_client, _public_resolver, _request_semaphore
    if _aiohttp_client is not None and not _aiohttp_client.closed:
        await _aiohttp_client.close()
    _aiohttp_client = None
    _public_resolver = None
    _request_semaphore = None


class Favicon:
    """Parse a website URL and fetch its favicon safely."""

    def __init__(self, url: str):
        self.scheme: Optional[str] = None
        self.domain: Optional[str] = None
        self.port: Optional[int] = None
        self.domain_md5: Optional[str] = None
        self.cache_identity: Optional[str] = None
        self.icon_url: Optional[str] = None
        self.icon_too_large = False
        self.path = '/'
        self.page_url: Optional[str] = None
        self._parse(url)

    def _parse(self, url: str) -> None:
        normalized, reason = _normalize_url_with_reason(_map_custom_protocol(url))
        if not normalized:
            logger.warning(
                'URL无效：%s；%s；返回默认图标',
                _url_for_log(url),
                _text_for_log(reason or '未知校验错误'),
            )
            return

        parsed = urlsplit(normalized)
        self.scheme = parsed.scheme
        self.domain = parsed.hostname
        self.port = parsed.port
        self.path = '/'
        self.cache_identity = self.get_base_url()
        if self.cache_identity:
            self.domain_md5 = hashlib.md5(
                self.cache_identity.encode('utf-8'),
                usedforsecurity=False,
            ).hexdigest()
            self.page_url = f'{self.cache_identity}/'

    def get_base_url(self) -> Optional[str]:
        if not self.domain or not self.scheme:
            return None
        display_host = f'[{self.domain}]' if ':' in self.domain else self.domain
        netloc = f'{display_host}:{self.port}' if self.port is not None else display_host
        return f'{self.scheme}://{netloc}'

    def get_icon_url(self, icon_path: str, default: bool = False) -> Optional[str]:
        if not self.page_url or not self.domain:
            self.icon_url = None
        elif default:
            self.icon_url = urljoin(self.get_base_url() + '/', 'favicon.ico')
        elif icon_path and icon_path.startswith('data:image'):
            self.icon_url = icon_path
        elif icon_path:
            self.icon_url = _normalize_url(urljoin(self.page_url, icon_path))
        else:
            self.icon_url = None
        return self.icon_url

    async def get_icon_file(
            self,
            icon_path: str,
            default: bool = False,
            retries: int = DEFAULT_RETRIES,
            timeout: float = DEFAULT_TIMEOUT,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        self.icon_too_large = False
        self.get_icon_url(icon_path, default)
        if not self.icon_url or not self.domain:
            return None, None

        try:
            if self.icon_url.startswith('data:image'):
                separator_index = self.icon_url.find(',')
                if separator_index < 0:
                    return None, None
                metadata = self.icon_url[:separator_index]
                payload_start = separator_index + 1
                if ';base64' in metadata.lower():
                    max_encoded_length = 4 * ((setting.MAX_ICON_BYTES + 2) // 3)
                    if len(self.icon_url) - payload_start > max_encoded_length:
                        self.icon_too_large = True
                        return None, None
                    payload = self.icon_url[payload_start:]
                    content = base64.b64decode(payload, validate=True)
                else:
                    payload = self.icon_url[payload_start:]
                    content = unquote_to_bytes(payload)
                content_type = metadata[5:].split(';', 1)[0].lower()
                if len(content) > setting.MAX_ICON_BYTES:
                    self.icon_too_large = True
                    return None, None
            else:
                content, content_type = await _req_get(
                    self.icon_url,
                    retries=retries,
                    timeout=timeout,
                    max_bytes=setting.MAX_ICON_BYTES,
                )

            if content and helpers.is_image(content):
                return content, filetype.guess_mime(content) or content_type
        except ResponseTooLargeError:
            self.icon_too_large = True
            return None, None
        except Exception as exc:
            logger.warning(
                '候选异常：%s；%s；继续下一来源',
                _url_for_log(self.icon_url),
                _exception_for_log(exc),
            )
        return None, None

    async def req_get(
            self,
            retries: int = DEFAULT_RETRIES,
            timeout: float = DEFAULT_TIMEOUT,
    ) -> Optional[bytes]:
        if not self.page_url:
            return None
        try:
            content, content_type = await _req_get(
                self.page_url,
                retries=retries,
                timeout=timeout,
                max_bytes=setting.MAX_HTML_BYTES,
            )
        except ResponseTooLargeError:
            return None
        if not content:
            return None
        if content_type and any(item in content_type for item in ('html', 'text', 'xml')):
            return content
        if content.lstrip().startswith((b'<!doctype html', b'<html', b'<?xml')):
            return content
        return None


async def _read_limited(response: aiohttp.ClientResponse, max_bytes: int) -> Optional[bytes]:
    content_length = response.content_length
    if content_length is not None and content_length > max_bytes:
        logger.debug(
            '响应过大：%s；大小=%d；上限=%d；中止候选',
            _url_for_log(str(response.url)),
            content_length,
            max_bytes,
        )
        raise ResponseTooLargeError

    content = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        content.extend(chunk)
        if len(content) > max_bytes:
            logger.debug(
                '响应过大：%s；上限=%d；中止候选',
                _url_for_log(str(response.url)),
                max_bytes,
            )
            raise ResponseTooLargeError
    return bytes(content)


async def _req_get(
        url: str,
        domain: Optional[str] = None,
        retries: int = DEFAULT_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = setting.MAX_ICON_BYTES,
) -> Tuple[Optional[bytes], Optional[str]]:
    del domain  # Retained for compatibility with the previous internal API.
    normalized, reason = _normalize_url_with_reason(url)
    if not normalized:
        logger.warning(
            '出站URL无效：%s；%s；中止候选',
            _url_for_log(url),
            _text_for_log(reason or '未知校验错误'),
        )
        return None, None
    if await blacklist_service.is_blocked(normalized):
        logger.warning(
            '出站请求被网址黑名单阻止：%s；中止候选',
            _url_for_log(normalized),
        )
        return None, None

    await initialize_http_client()
    client = _aiohttp_client
    semaphore = _request_semaphore
    if client is None or semaphore is None:
        raise RuntimeError('HTTP 客户端初始化未完成')

    for attempt in range(retries + 1):
        current_url = normalized
        try:
            for redirect_count in range(setting.HTTP_MAX_REDIRECTS + 1):
                if await blacklist_service.is_blocked(current_url):
                    logger.warning(
                        '出站请求被网址黑名单阻止：%s；中止候选',
                        _url_for_log(current_url),
                    )
                    return None, None
                if setting.HTTP_TRUST_ENV:
                    await _validate_proxy_destination(current_url)
                async with semaphore:
                    async with client.get(
                            current_url,
                            headers=header.get_header(),
                            allow_redirects=False,
                            ssl=False,
                            timeout=aiohttp.ClientTimeout(
                                total=timeout,
                                connect=setting.HTTP_CONNECT_TIMEOUT,
                            ),
                    ) as response:
                        if response.status in _redirect_statuses:
                            if redirect_count >= setting.HTTP_MAX_REDIRECTS:
                                logger.warning(
                                    '重定向过多：%s；上限=%d；中止候选',
                                    _url_for_log(current_url),
                                    setting.HTTP_MAX_REDIRECTS,
                                )
                                return None, None
                            location = response.headers.get('Location')
                            redirect_url = urljoin(current_url, location or '')
                            next_url, redirect_reason = _normalize_url_with_reason(redirect_url)
                            if not next_url:
                                logger.warning(
                                    '重定向被阻止：%s -> %s；%s；中止候选',
                                    _url_for_log(current_url),
                                    _url_for_log(redirect_url),
                                    _text_for_log(redirect_reason or '重定向目标无效'),
                                )
                                return None, None
                            current_url = next_url
                            continue

                        if not 200 <= response.status < 300:
                            logger.debug(
                                '请求失败：%s；HTTP %d；继续下一来源',
                                _url_for_log(current_url),
                                response.status,
                            )
                            return None, None

                        content = await _read_limited(response, max_bytes)
                        if content is None:
                            return None, None
                        content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                        return content, content_type or None
        except ResponseTooLargeError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            if attempt >= retries:
                logger.debug(
                    '请求异常：%s；%s；继续下一来源',
                    _url_for_log(current_url),
                    _exception_for_log(exc),
                )
                break
            await asyncio.sleep(0)
    return None, None


async def _validate_proxy_destination(url: str) -> None:
    """Validate local DNS answers before handing a hostname to a configured proxy."""
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise OSError('出站网址缺少主机名')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        resolver = _public_resolver
        if resolver is None:
            raise RuntimeError('HTTP DNS 解析器尚未初始化')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        await resolver.resolve_public(host, port, socket.AF_UNSPEC)
    else:
        if not _is_allowed_target_ip(str(address)):
            raise OSError(f'代理目标 {host} 是禁止访问的非公网地址')


def _failure_path(identity: str) -> str:
    digest = hashlib.md5(identity.encode('utf-8'), usedforsecurity=False).hexdigest()
    return os.path.join(setting.failed_urls_dir, digest[:2], f'{digest}.txt')


def _failure_candidates(identity: str) -> list[str]:
    paths = [_failure_path(identity)]
    sha256_digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    paths.append(os.path.join(setting.failed_urls_dir, sha256_digest[:2], f'{sha256_digest}.txt'))
    try:
        domain = urlsplit(identity).hostname or identity
        domain_digest = hashlib.md5(
            domain.encode('utf-8'),
            usedforsecurity=False,
        ).hexdigest()
        paths.append(os.path.join(setting.failed_urls_dir, domain_digest[:1], f'{domain_digest}.txt'))
    except (UnicodeError, ValueError):
        pass
    return list(dict.fromkeys(paths))


def reset_failed_url_counts() -> None:
    """Reset process-local consecutive failure counts for a new service start."""
    with _negative_memory_lock:
        _negative_failure_counts.clear()


def _trim_negative_cache(cache: OrderedDict) -> None:
    limit = max(0, setting.NEGATIVE_MEMORY_CACHE_MAX_ITEMS)
    while cache and len(cache) > limit:
        cache.popitem(last=False)


def _next_failure_duration(identity: str) -> int:
    minimum = max(1, setting.FAILED_URL_EXPIRE_MIN)
    maximum = max(minimum, setting.FAILED_URL_EXPIRE_MAX)
    ratio = max(1.0, setting.FAILED_URL_EXPIRE_RATIO)
    with _negative_memory_lock:
        failure_count = _negative_failure_counts.get(identity, 0) + 1
        _negative_failure_counts[identity] = failure_count
        _negative_failure_counts.move_to_end(identity)
        _trim_negative_cache(_negative_failure_counts)
    try:
        duration = int(minimum * pow(ratio, failure_count - 1))
    except (OverflowError, ValueError):
        return maximum
    return min(maximum, max(minimum, duration))


def failed_url_ttl(identity: str) -> int:
    """Return the remaining negative-cache lifetime in seconds."""
    if not identity:
        return 0
    now = time.time()
    with _negative_memory_lock:
        memory_expiry = _negative_memory_cache.get(identity)
        if memory_expiry and memory_expiry > now:
            _negative_memory_cache.move_to_end(identity)
            return max(1, int(memory_expiry - now))
        _negative_memory_cache.pop(identity, None)

    current_path = _failure_path(identity)
    path = next((candidate for candidate in _failure_candidates(identity) if os.path.exists(candidate)), current_path)
    try:
        if not os.path.exists(path):
            return 0
        content = FileUtil.read_file(path, mode='r')
        try:
            record = json.loads(content or '')
            expires_at = float(record['expires_at'])
            created_at = float(record.get('created_at', os.path.getmtime(path)))
            duration = int(record.get('ttl', max(1, expires_at - created_at)))
        except (AttributeError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            # Backward compatibility for the previous text-only failure files.
            created_at = os.path.getmtime(path)
            duration = setting.FAILED_URL_EXPIRE_MIN
            expires_at = created_at + duration

        remaining = int(expires_at - time.time())
        if remaining > 0:
            if path != current_path:
                migrated = json.dumps({
                    'identity': identity,
                    'created_at': created_at,
                    'expires_at': expires_at,
                    'ttl': duration,
                }, ensure_ascii=True, separators=(',', ':'))
                if FileUtil.write_file(current_path, migrated, atomic=True):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            with _negative_memory_lock:
                _negative_memory_cache[identity] = expires_at
                _negative_memory_cache.move_to_end(identity)
                _trim_negative_cache(_negative_memory_cache)
            return remaining
        os.remove(path)
    except OSError as exc:
        logger.warning(
            '负缓存读取失败：%s；%s；重新抓取',
            _url_for_log(identity),
            _exception_for_log(exc),
        )
    return 0


def add_failed_url(identity: str) -> int:
    if not identity:
        return 0
    try:
        existing_ttl = failed_url_ttl(identity)
        if existing_ttl > 0:
            return existing_ttl

        path = _failure_path(identity)
        duration = _next_failure_duration(identity)
        now = time.time()
        record = json.dumps({
            'identity': identity,
            'created_at': now,
            'expires_at': now + duration,
            'ttl': duration,
        }, ensure_ascii=True, separators=(',', ':'))
        if FileUtil.write_file(path, record, atomic=True):
            with _negative_memory_lock:
                _negative_memory_cache[identity] = now + duration
                _negative_memory_cache.move_to_end(identity)
                _trim_negative_cache(_negative_memory_cache)
            return duration
    except Exception as exc:
        logger.error(
            '负缓存写入失败：%s；%s；不缓存失败结果',
            _url_for_log(identity),
            _exception_for_log(exc),
        )
    return 0


def clear_failed_url(identity: str) -> None:
    if not identity:
        return
    with _negative_memory_lock:
        _negative_memory_cache.pop(identity, None)
        _negative_failure_counts.pop(identity, None)
    for path in _failure_candidates(identity):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning(
                '负缓存清理失败：%s；%s；继续使用有效图标',
                _url_for_log(identity),
                _exception_for_log(exc),
            )


def is_failed_url(identity: str) -> bool:
    return failed_url_ttl(identity) > 0


def _check_internal(domain: str) -> bool:
    """Compatibility helper: True only when every DNS answer is allowed."""
    try:
        addresses = socket.getaddrinfo(domain, None)
        ips = {item[4][0] for item in addresses}
        return bool(ips) and all(_is_allowed_target_ip(ip) for ip in ips)
    except OSError:
        return False


def _check_url(domain: str) -> bool:
    return _normalize_url(f'http://{domain}') is not None and _check_internal(domain)
