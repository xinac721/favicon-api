# -*- coding: utf-8 -*-

import logging
import os
from typing import Optional

import urllib3
from fastapi import APIRouter, Request, Query, BackgroundTasks
from fastapi.responses import Response, FileResponse

import setting
from favicon_app.routes import favicon_service
from favicon_app.utils.file_util import FileUtil

urllib3.disable_warnings()
logging.captureWarnings(True)
logger = logging.getLogger(__name__)

_icon_root_path = setting.icon_root_path
_default_icon_path = setting.default_icon_path

# 创建FastAPI路由器
favicon_router = APIRouter(prefix="/icon", tags=["favicon"])


@favicon_router.get('/')
async def get_favicon(
        request: Request,
        bg_tasks: BackgroundTasks,
        url: Optional[str] = Query(None, description="网址：eg. https://www.baidu.com"),
        refresh: Optional[str] = Query(None, include_in_schema=False),
):
    """获取网站图标"""
    if not url:
        return FileResponse("templates/index.html")
    return await favicon_service.get_favicon_handler(request, bg_tasks, url, refresh)


@favicon_router.get('/default')
async def get_default_icon():
    """获取默认图标"""
    return favicon_service.get_default()


@favicon_router.get('/referer', include_in_schema=False)
async def get_referrer(unique: Optional[str] = Query(None)):
    """获取请求来源信息，带unique参数时会进行去重处理"""
    content = 'None'
    _path = os.path.join(_icon_root_path, 'data', 'referer.txt')

    if os.path.exists(_path):
        try:
            content = FileUtil.read_file(_path, mode='r') or 'None'

            if unique in ['true', '1']:
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                unique_lines = list(set(lines))
                unique_content = '\n'.join(unique_lines)
                FileUtil.write_file(_path, unique_content, mode='w')
                content = unique_content
        except Exception as e:
            logger.error(f"读取referer文件失败: {e}")
    return Response(content=content, media_type="text/plain")
