# -*- coding: utf-8 -*-

import asyncio
import ipaddress
import json
import logging
import os
import re
import uuid
from collections import Counter
from typing import Optional
from urllib.parse import urlsplit

import setting
from favicon_app.utils.file_util import FileUtil

logger = logging.getLogger(__name__)

_safe_boot_id = re.compile(r'[^a-zA-Z0-9_-]')
_domain_label = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$', re.I)
_sources: Counter[str] = Counter()
_targets: Counter[str] = Counter()
_source_total = 0
_target_total = 0
_snapshot_task: Optional[asyncio.Task] = None
_snapshot_file: Optional[str] = None
_snapshot_lock = asyncio.Lock()
_worker_pid: Optional[int] = None
_worker_id: Optional[str] = None


def normalize_origin(value: Optional[str]) -> Optional[str]:
    """Return a display-safe HTTP origin with default ports removed."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ('http', 'https') or not parsed.hostname:
            return None
        host = parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or any(not _domain_label.fullmatch(label) for label in host.split('.')):
                return None
        port = parsed.port
        if port == (80 if scheme == 'http' else 443):
            port = None
        display_host = f'[{host}]' if ':' in host else host
        netloc = f'{display_host}:{port}' if port is not None else display_host
        return f'{scheme}://{netloc}'
    except (UnicodeError, ValueError):
        return None


def _increment(counter: Counter[str], key: str) -> None:
    counter[key] += 1
    limit = max(setting.STATS_TOP_LIMIT, setting.STATS_MAX_ITEMS)
    if len(counter) > limit * 2:
        retained = counter.most_common(limit)
        counter.clear()
        counter.update(dict(retained))


def record_request(target: str, source: Optional[str] = None) -> None:
    """Record one validated favicon API request without performing I/O."""
    global _source_total, _target_total
    target_origin = normalize_origin(target)
    if not target_origin:
        return

    _increment(_targets, target_origin)
    _target_total += 1

    source_origin = normalize_origin(source)
    if source_origin:
        _increment(_sources, source_origin)
        _source_total += 1


def _boot_directory() -> str:
    boot_id = _safe_boot_id.sub('_', setting.STATS_BOOT_ID)[:128] or 'default'
    return os.path.join(setting.icon_root_path, 'data', 'runtime_stats', boot_id)


def _snapshot_payload() -> dict:
    snapshot_limit = max(setting.STATS_TOP_LIMIT, setting.STATS_SNAPSHOT_ITEMS)
    return {
        'started_at': setting.STATS_STARTED_AT,
        'source_total': _source_total,
        'target_total': _target_total,
        'sources': dict(_sources.most_common(snapshot_limit)),
        'targets': dict(_targets.most_common(snapshot_limit)),
    }


def _write_snapshot(path: str, payload: dict) -> None:
    content = json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
    if not FileUtil.write_file(path, content, atomic=True):
        logger.warning('Failed to write ranking snapshot: %s', path)


async def flush_snapshot() -> None:
    if not _snapshot_file:
        return
    async with _snapshot_lock:
        write_task = asyncio.create_task(asyncio.to_thread(
            _write_snapshot,
            _snapshot_file,
            _snapshot_payload(),
        ))
        try:
            await asyncio.shield(write_task)
        except asyncio.CancelledError:
            await write_task
            raise


async def _snapshot_loop() -> None:
    while True:
        await asyncio.sleep(max(0.1, setting.STATS_SNAPSHOT_INTERVAL))
        await flush_snapshot()


async def start_stats() -> None:
    global _source_total, _target_total, _snapshot_file, _snapshot_task, _worker_pid, _worker_id
    if _snapshot_task is not None:
        return
    _sources.clear()
    _targets.clear()
    _source_total = 0
    _target_total = 0
    current_pid = os.getpid()
    if _worker_pid != current_pid or not _worker_id:
        _worker_pid = current_pid
        _worker_id = f'{current_pid}-{uuid.uuid4().hex}'
    _snapshot_file = os.path.join(_boot_directory(), f'{_worker_id}.json')
    await flush_snapshot()
    _snapshot_task = asyncio.create_task(_snapshot_loop())


async def stop_stats() -> None:
    global _snapshot_file, _snapshot_task
    task = _snapshot_task
    if task is None:
        return
    _snapshot_task = None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await flush_snapshot()
    _snapshot_file = None


def _read_aggregate(directory: str) -> dict:
    sources: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    source_total = 0
    target_total = 0
    try:
        entries = list(os.scandir(directory))
    except OSError:
        entries = []

    for entry in entries:
        if not entry.is_file() or not entry.name.endswith('.json'):
            continue
        try:
            if entry.stat().st_size > 2 * 1024 * 1024:
                continue
            with open(entry.path, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            source_total += max(0, int(payload.get('source_total', 0)))
            target_total += max(0, int(payload.get('target_total', 0)))
            sources.update({str(key): int(value) for key, value in payload.get('sources', {}).items()})
            targets.update({str(key): int(value) for key, value in payload.get('targets', {}).items()})
        except (AttributeError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning('Ignoring invalid ranking snapshot %s: %s', entry.path, exc)

    limit = max(1, setting.STATS_TOP_LIMIT)

    def ranked(counter: Counter[str]) -> list[dict[str, object]]:
        values = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return [{'url': url, 'count': count} for url, count in values]

    return {
        'started_at': setting.STATS_STARTED_AT,
        'total_source_requests': source_total,
        'total_target_requests': target_total,
        'sources': ranked(sources),
        'targets': ranked(targets),
    }


async def get_stats() -> dict:
    await flush_snapshot()
    return await asyncio.to_thread(_read_aggregate, _boot_directory())
