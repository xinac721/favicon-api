# -*- coding: utf-8 -*-

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

import setting
from favicon_app.routes import favicon_router
from favicon_app.routes import favicon_service
from favicon_app.models import favicon
from favicon_app.services import blacklist_service, stats_service
from favicon_app.utils.referer_log import append_rotating_line

logger = logging.getLogger(__name__)

# 站点的 favicon.ico 图标
favicon_icon_file = setting.favicon_icon_file
# 默认的站点图标
default_icon_file = setting.default_icon_file
# referer日志文件路径
referer_log_file = setting.referer_log_file


def _sanitize_referer(value: str) -> str:
    try:
        parsed = urlsplit(value[:2048])
        scheme = parsed.scheme.lower()
        if scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        host = parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        display_host = f'[{host}]' if ':' in host else host
        port = parsed.port
        netloc = f'{display_host}:{port}' if port is not None else display_host
        return urlunsplit((scheme, netloc, parsed.path, '', ''))
    except (UnicodeError, ValueError):
        return ''


def _write_referer(value: str) -> None:
    try:
        sanitized = _sanitize_referer(value)
        if not sanitized:
            return
        append_rotating_line(
            referer_log_file,
            f'{sanitized}\n',
            setting.REFERER_LOG_MAX_BYTES,
        )
    except OSError as exc:
        logger.warning('Failed to write referer log: %s', exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        favicon.reset_failed_url_counts()
        await blacklist_service.initialize()
        await favicon.initialize_http_client()
        await favicon_service.start_refresh_workers()
        await stats_service.start_stats()
        yield
    finally:
        for cleanup in (
                stats_service.stop_stats,
                favicon_service.stop_refresh_workers,
                favicon.close_http_client,
        ):
            try:
                await cleanup()
            except Exception:
                logger.exception('Application cleanup failed in %s', cleanup.__name__)


# fastapi
app = FastAPI(
    title="Favicon API",
    description="获取网站favicon图标",
    version="4.1",
    lifespan=lifespan,
)
app.include_router(favicon_router)
app.mount(
    f"{setting.ICON_ROUTE_PREFIX_PATH}/assets",
    StaticFiles(directory=os.path.join(setting.icon_root_path, "templates", "assets")),
    name="frontend-assets",
)


@app.middleware("http")
async def log_referer(request: Request, call_next):
    response = await call_next(request)
    if setting.ENABLE_REFERER_LOG:
        referer = request.headers.get('referer')
        if referer:
            await asyncio.to_thread(_write_referer, referer)
    return response


@app.get("/")
async def root():
    return {
        "message": (
            "Welcome to Favicon API! Use "
            f"{setting.ICON_ROUTE_PREFIX}?url=api.xinac.net to get favicon."
        )
    }


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@app.get("/favicon.ico", summary="favicon.ico", tags=["default"])
async def favicon_ico():
    return Response(content=favicon_icon_file, media_type="image/x-icon")


@app.get("/favicon.png", summary="favicon.png", tags=["default"])
async def favicon_png():
    return Response(content=default_icon_file, media_type="image/png")
