# -*- coding: utf-8 -*-

import asyncio
import ipaddress
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import setting

logger = logging.getLogger(__name__)

_domain_label = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$', re.I)
_inline_comment = re.compile(r'\s+#')


@dataclass(frozen=True)
class BlacklistRules:
    domains: frozenset[str] = frozenset()
    wildcard_domains: frozenset[str] = frozenset()
    exact_hosts: frozenset[str] = frozenset()
    allowed_domains: frozenset[str] = frozenset()
    allowed_exact_hosts: frozenset[str] = frozenset()

    @property
    def count(self) -> int:
        return sum((
            len(self.domains),
            len(self.wildcard_domains),
            len(self.exact_hosts),
            len(self.allowed_domains),
            len(self.allowed_exact_hosts),
        ))

    @staticmethod
    def _matches_domain(
            host: str,
            domains: frozenset[str],
            exact_hosts: frozenset[str]) -> bool:
        if host in exact_hosts or host in domains:
            return True
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass

        labels = host.split('.')
        for index in range(1, len(labels)):
            parent = '.'.join(labels[index:])
            if parent in domains:
                return True
        return False

    def matches(self, host: str) -> bool:
        if self._matches_domain(host, self.allowed_domains, self.allowed_exact_hosts):
            return False
        if self._matches_domain(host, self.domains, self.exact_hosts):
            return True

        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        labels = host.split('.')
        return any(
            '.'.join(labels[index:]) in self.wildcard_domains
            for index in range(1, len(labels))
        )


_rules = BlacklistRules()
_state_lock = threading.Lock()
_loaded_path: str | None = None
_loaded_signature: tuple[int, int, int] | None = None
_next_check_at = 0.0
_has_loaded = False
_missing_notice_path: str | None = None


def _normalize_host(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = urlsplit(text if '://' in text else f'//{text}')
        if parsed.scheme and parsed.scheme.lower() not in ('http', 'https'):
            return None
        if parsed.username or parsed.password or not parsed.hostname:
            return None
        # Accessing port validates malformed and out-of-range values even though
        # blacklist rules intentionally apply across all ports and schemes.
        parsed.port
        host = parsed.hostname.rstrip('.')
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            host = host.encode('idna').decode('ascii').lower()
            if len(host) > 253 or any(
                    not _domain_label.fullmatch(label) for label in host.split('.')):
                return None
            return host
    except (UnicodeError, ValueError):
        return None


def _parse_rules(content: str, max_entries: int) -> BlacklistRules:
    domains: set[str] = set()
    wildcard_domains: set[str] = set()
    exact_hosts: set[str] = set()
    allowed_domains: set[str] = set()
    allowed_exact_hosts: set[str] = set()
    active_line_count = 0

    def add_rule(target: set[str], value: str, line_number: int) -> None:
        host = _normalize_host(value)
        if not host:
            raise ValueError(f'第 {line_number} 行不是有效的主机名')
        target.add(host)
        count = sum((
            len(domains),
            len(wildcard_domains),
            len(exact_hosts),
            len(allowed_domains),
            len(allowed_exact_hosts),
        ))
        if count > max_entries:
            raise ValueError(f'规则条目超过上限 {max_entries}')

    for line_number, raw_line in enumerate(content.splitlines(), 1):
        value = raw_line.strip()
        if not value or value.startswith(('#', '!')):
            continue
        if value.startswith('[') and value.endswith(']'):
            continue
        comment_match = _inline_comment.search(value)
        if comment_match:
            value = value[:comment_match.start()].rstrip()
            if not value:
                continue
        active_line_count += 1

        is_exception = value.startswith('@@')
        if is_exception:
            value = value[2:].strip()

        if value.startswith('||') and value.endswith('^'):
            adguard_host = value[2:-1].strip()
            if (
                    not adguard_host
                    or any(marker in adguard_host for marker in (
                        '*', '|', '^', '$', '/', '#', '?', ':', '@', '[', ']',
                    ))
                    or not _normalize_host(adguard_host)
            ):
                continue
            target = allowed_domains if is_exception else domains
            add_rule(target, adguard_host, line_number)
            continue

        if is_exception:
            if any(character in value for character in ('*', '|', '^', '$', '/')):
                continue
            add_rule(allowed_exact_hosts, value, line_number)
            continue

        parts = value.split()
        if len(parts) > 1:
            try:
                hosts_address = ipaddress.ip_address(parts[0])
            except ValueError:
                hosts_address = None
            if hosts_address and (hosts_address.is_unspecified or hosts_address.is_loopback):
                for host_value in parts[1:]:
                    add_rule(exact_hosts, host_value, line_number)
                continue
            if hosts_address:
                # AdGuard also supports DNS rewrite hosts entries. They are not
                # blocking rules and therefore do not belong in this blacklist.
                continue
            raise ValueError(f'第 {line_number} 行不是有效的 AdGuard 规则')

        # Keep the previous local syntax readable while new snapshots use
        # standard AdGuard DNS rules.
        if value.startswith('='):
            add_rule(exact_hosts, value[1:].strip(), line_number)
        elif value.startswith('*.'):
            add_rule(wildcard_domains, value[2:].strip(), line_number)
        elif '://' in value:
            add_rule(domains, value, line_number)
        elif any(marker in value for marker in ('*', '|', '^', '$', '/', '#')):
            # URL-path, regular-expression, cosmetic, and modifier rules cannot
            # be represented by the service's host-only policy without widening
            # their scope, so they are intentionally ignored.
            continue
        else:
            add_rule(exact_hosts, value, line_number)

    rule_count = sum((
        len(domains),
        len(wildcard_domains),
        len(exact_hosts),
        len(allowed_domains),
        len(allowed_exact_hosts),
    ))
    if active_line_count and not rule_count:
        raise ValueError('文件不包含可用的 AdGuard 主机规则')

    return BlacklistRules(
        domains=frozenset(domains),
        wildcard_domains=frozenset(wildcard_domains),
        exact_hosts=frozenset(exact_hosts),
        allowed_domains=frozenset(allowed_domains),
        allowed_exact_hosts=frozenset(allowed_exact_hosts),
    )


def _blacklist_path() -> str:
    return os.path.abspath(setting.URL_BLACKLIST_FILE)


def _reload_due() -> bool:
    return (
        not _has_loaded
        or _loaded_path != _blacklist_path()
        or time.monotonic() >= _next_check_at
    )


def _handle_missing_file_locked(path: str) -> bool:
    global _rules, _loaded_path, _loaded_signature, _has_loaded
    global _missing_notice_path

    should_notify = _missing_notice_path != path
    _missing_notice_path = path
    if _has_loaded and _loaded_path == path and _loaded_signature is not None:
        if should_notify:
            logger.error('网址黑名单文件已丢失：%s；保留上次有效规则', path)
        return False

    _rules = BlacklistRules()
    _loaded_path = path
    _loaded_signature = None
    _has_loaded = True
    if should_notify:
        logger.info('网址黑名单文件不存在：%s；使用空规则集', path)
    return True


def _reload_if_due(force: bool = False) -> bool:
    global _rules, _loaded_path, _loaded_signature, _next_check_at, _has_loaded
    global _missing_notice_path

    path = _blacklist_path()
    now = time.monotonic()
    with _state_lock:
        if not force and _has_loaded and _loaded_path == path and now < _next_check_at:
            return True
        _next_check_at = now + setting.URL_BLACKLIST_RELOAD_INTERVAL

        try:
            stat_result = os.stat(path)
        except FileNotFoundError:
            return _handle_missing_file_locked(path)
        except OSError as exc:
            logger.error('网址黑名单检查失败：%s；%s；保留上次有效规则', path, exc)
            return False

        if stat_result.st_size > setting.URL_BLACKLIST_MAX_BYTES:
            _missing_notice_path = None
            logger.error(
                '网址黑名单过大：%s；大小=%d；上限=%d；保留上次有效规则',
                path,
                stat_result.st_size,
                setting.URL_BLACKLIST_MAX_BYTES,
            )
            return False

        signature = (stat_result.st_ino, stat_result.st_mtime_ns, stat_result.st_size)
        if _loaded_path == path and _loaded_signature == signature:
            _missing_notice_path = None
            _has_loaded = True
            return True

        try:
            with open(path, 'rb') as file:
                raw_content = file.read(setting.URL_BLACKLIST_MAX_BYTES + 1)
            _missing_notice_path = None
            if len(raw_content) > setting.URL_BLACKLIST_MAX_BYTES:
                raise ValueError(f'文件超过 {setting.URL_BLACKLIST_MAX_BYTES} 字节')
            content = raw_content.decode('utf-8-sig')
            new_rules = _parse_rules(content, setting.URL_BLACKLIST_MAX_ENTRIES)
        except FileNotFoundError:
            return _handle_missing_file_locked(path)
        except (OSError, UnicodeError, ValueError) as exc:
            logger.error('网址黑名单加载失败：%s；%s；保留上次有效规则', path, exc)
            return False

        _rules = new_rules
        _loaded_path = path
        _loaded_signature = signature
        _has_loaded = True
        logger.info('网址黑名单已加载：%s；规则=%d', path, new_rules.count)
        return True


async def initialize() -> None:
    if setting.URL_BLACKLIST_ENABLED:
        loaded = await asyncio.to_thread(_reload_if_due, True)
        if not loaded:
            raise RuntimeError('网址黑名单初始加载失败')


async def is_blocked(value: object) -> bool:
    if not setting.URL_BLACKLIST_ENABLED:
        return False
    if _reload_due():
        await asyncio.to_thread(_reload_if_due)
    host = _normalize_host(value)
    return bool(host and _rules.matches(host))


def reset_cache() -> None:
    """Clear process-local state; intended for tests and controlled reloads."""
    global _rules, _loaded_path, _loaded_signature, _next_check_at, _has_loaded
    global _missing_notice_path
    with _state_lock:
        _rules = BlacklistRules()
        _loaded_path = None
        _loaded_signature = None
        _next_check_at = 0.0
        _has_loaded = False
        _missing_notice_path = None
