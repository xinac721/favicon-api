# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Query, Header, HTTPException, Request
from fastapi.responses import Response, FileResponse, JSONResponse

import setting
from favicon_app.routes import favicon_service
from favicon_app.services import stats_service
from favicon_app.utils.referer_log import read_referers

logger = logging.getLogger(__name__)

_icon_root_path = setting.icon_root_path
_admin_response_headers = {
    'Cache-Control': 'private, no-store',
    'Vary': 'X-Admin-Token',
    'X-Content-Type-Options': 'nosniff',
    'X-Robots-Tag': 'noindex, nofollow',
}

# 创建FastAPI路由器
favicon_router = APIRouter(prefix=setting.ICON_ROUTE_PREFIX_PATH, tags=["favicon"])


@favicon_router.get('/')
async def get_favicon(
        request: Request,
        url: Optional[str] = Query(None, description="网址：eg. https://www.baidu.com"),
        refresh: Optional[str] = Query(None, include_in_schema=False),
        track: Optional[str] = Query(None, include_in_schema=False),
):
    """获取网站图标"""
    if not url:
        return FileResponse(os.path.join(_icon_root_path, "templates", "index.html"))
    try:
        should_track = (track or '').lower() not in ('0', 'false', 'no')
        source = request.headers.get('referer') or request.headers.get('origin')
        return await favicon_service.get_favicon_handler(url, refresh, should_track, source)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception('图标路由异常；返回默认图')
        return favicon_service.get_default(cache_time=0, cache_status='FALLBACK')


@favicon_router.get('/default')
async def get_default_icon():
    """获取默认图标"""
    return favicon_service.get_default()
