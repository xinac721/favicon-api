# -*- coding: utf-8 -*-

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import Response

import setting
from favicon_app.routes import favicon_router
from favicon_app.utils.file_util import FileUtil

logger = logging.getLogger(__name__)

# 获取当前所在目录
_current_dir = os.path.dirname(os.path.abspath(__file__))
# 站点的 favicon.ico 图标
favicon_icon_file = setting.favicon_icon_file
# 默认的站点图标
default_icon_file = setting.default_icon_file
# referer日志文件路径
referer_log_file = setting.referer_log_file

# fastapi
app = FastAPI(title="Favicon API", description="获取网站favicon图标", version="3.0")
app.include_router(favicon_router)


@app.middleware("http")
async def log_referer(request: Request, call_next):
    _referer = request.headers.get('referrer') or request.headers.get('referer')
    if _referer:
        FileUtil.write_file(referer_log_file, '%s\n' % _referer, mode='a')
    response = await call_next(request)
    return response


@app.get("/")
async def root():
    return {"message": "Welcome to Favicon API! Use /icon/?url=example.com to get favicon."}


@app.get("/favicon.ico", summary="favicon.ico", tags=["default"])
async def favicon_ico():
    return Response(content=favicon_icon_file, media_type="image/x-icon")


@app.get("/favicon.png", summary="favicon.png", tags=["default"])
async def favicon_png():
    return Response(content=default_icon_file, media_type="image/png")
