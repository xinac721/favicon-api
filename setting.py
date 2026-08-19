# -*- coding: utf-8 -*-

import os
import re
import uuid
from datetime import datetime, timezone

from favicon_app.utils.file_util import FileUtil
from favicon_app.utils.env import env_bool, env_float, env_int

# 获取当前所在目录
_current_dir = os.path.dirname(os.path.abspath(__file__))


def _normalize_icon_route_prefix(value: str) -> str:
    text = (value or '').strip()
    if not text or text == '/':
        return '/'
    segments = [segment for segment in text.split('/') if segment]
    if not segments or any(not re.fullmatch(r'[A-Za-z0-9._~-]+', segment) for segment in segments):
        raise ValueError('ICON_ROUTE_PREFIX must contain URL-safe path segments')
    return f"/{'/'.join(segments)}/"


ICON_ROUTE_PREFIX = _normalize_icon_route_prefix(os.getenv('ICON_ROUTE_PREFIX', '/icon/'))
ICON_ROUTE_PREFIX_PATH = '' if ICON_ROUTE_PREFIX == '/' else ICON_ROUTE_PREFIX.rstrip('/')

# icon 存储的绝对路径
icon_root_path = _current_dir
# 站点的 favicon.ico 图标
favicon_icon_file = FileUtil.read_file(os.path.join(icon_root_path, 'favicon.ico'), mode='rb')
# 默认的站点图标
default_icon_path = os.path.join(icon_root_path, 'favicon.png')
default_icon_file = FileUtil.read_file(default_icon_path, mode='rb')
# 定义referer日志文件路径
referer_log_file = os.path.join(icon_root_path, 'data', 'referer.txt')
# Referer 可能包含敏感查询参数，默认不记录。
ENABLE_REFERER_LOG = env_bool('ENABLE_REFERER_LOG', False)
REFERER_LOG_MAX_BYTES = env_int('REFERER_LOG_MAX_BYTES', 10 * 1024 * 1024, minimum=1)
REFERER_ADMIN_TOKEN = os.getenv('REFERER_ADMIN_TOKEN', '')
# 定义失败URL日志文件路径
# failed_urls_file = os.path.join(icon_root_path, 'data', 'failedurls.txt')
# 定义失败URL存储目录
failed_urls_dir = os.path.join(icon_root_path, 'data', 'failed_urls')

# 默认禁止请求私有、回环、链路本地等非公网地址。
ALLOW_PRIVATE_NETWORK = env_bool('ALLOW_PRIVATE_NETWORK', False)

# 网址黑名单。相对路径以项目根目录为基准；启动时文件不存在按空规则集处理。
URL_BLACKLIST_ENABLED = env_bool('URL_BLACKLIST_ENABLED', True)
_url_blacklist_file = os.getenv(
    'URL_BLACKLIST_FILE',
    os.path.join('data', 'url_blacklist.txt'),
).strip()
if not _url_blacklist_file:
    raise ValueError('URL_BLACKLIST_FILE must not be empty')
URL_BLACKLIST_FILE = (
    _url_blacklist_file
    if os.path.isabs(_url_blacklist_file)
    else os.path.join(_current_dir, _url_blacklist_file)
)
URL_BLACKLIST_RELOAD_INTERVAL = env_float(
    'URL_BLACKLIST_RELOAD_INTERVAL',
    5,
    minimum=0,
)
URL_BLACKLIST_MAX_BYTES = env_int(
    'URL_BLACKLIST_MAX_BYTES',
    10 * 1024 * 1024,
    minimum=1,
)
URL_BLACKLIST_MAX_ENTRIES = env_int(
    'URL_BLACKLIST_MAX_ENTRIES',
    250000,
    minimum=1,
)
URL_BLACKLIST_RESPONSE = os.getenv('URL_BLACKLIST_RESPONSE', 'svg').strip().lower()
if URL_BLACKLIST_RESPONSE not in ('svg', 'default'):
    raise ValueError('URL_BLACKLIST_RESPONSE must be svg or default')

# 时间常量
time_of_1_minus = 1 * 60
time_of_5_minus = 5 * time_of_1_minus
time_of_10_minus = 10 * time_of_1_minus
time_of_30_minus = 30 * time_of_1_minus

time_of_1_hours = 1 * 60 * 60
time_of_2_hours = 2 * time_of_1_hours
time_of_3_hours = 3 * time_of_1_hours
time_of_6_hours = 6 * time_of_1_hours
time_of_12_hours = 12 * time_of_1_hours

time_of_1_days = 1 * 24 * 60 * 60
time_of_7_days = 7 * time_of_1_days
time_of_15_days = 15 * time_of_1_days
time_of_30_days = 30 * time_of_1_days

# 连续失败按“首项 * 公比^(次数-1)”增加负缓存时长，并受最大值限制。
FAILED_URL_EXPIRE_MIN = env_int('FAILED_URL_EXPIRE_MIN', time_of_6_hours, minimum=1)
FAILED_URL_EXPIRE_MAX = env_int('FAILED_URL_EXPIRE_MAX', 72 * time_of_1_hours, minimum=1)
FAILED_URL_EXPIRE_RATIO = env_float('FAILED_URL_EXPIRE_RATIO', 2, minimum=1)
NEGATIVE_MEMORY_CACHE_MAX_ITEMS = env_int('NEGATIVE_MEMORY_CACHE_MAX_ITEMS', 50000, minimum=0)
if FAILED_URL_EXPIRE_MAX < FAILED_URL_EXPIRE_MIN:
    raise ValueError('FAILED_URL_EXPIRE_MAX must be at least FAILED_URL_EXPIRE_MIN')

# 抓取与缓存。缓存过了刷新周期后仍立即返回，由后台刷新。
MAX_ICON_BYTES = env_int('MAX_ICON_BYTES', 5 * 1024 * 1024, minimum=1)
MAX_HTML_BYTES = env_int('MAX_HTML_BYTES', 4 * 1024 * 1024, minimum=1)
HTTP_CONNECT_TIMEOUT = env_float('HTTP_CONNECT_TIMEOUT', 10, minimum=0.001)
HTTP_TOTAL_TIMEOUT = env_float('HTTP_TOTAL_TIMEOUT', 30, minimum=0.001)
HTTP_MAX_REDIRECTS = env_int('HTTP_MAX_REDIRECTS', 3, minimum=0)
HTTP_CONNECTION_LIMIT = env_int('HTTP_CONNECTION_LIMIT', 100, minimum=1)
HTTP_CONNECTION_LIMIT_PER_HOST = env_int('HTTP_CONNECTION_LIMIT_PER_HOST', 20, minimum=1)
HTTP_MAX_CONCURRENCY = env_int('HTTP_MAX_CONCURRENCY', 50, minimum=1)
# 启用后 aiohttp 从标准环境变量读取 HTTP(S) 代理和 NO_PROXY。
HTTP_TRUST_ENV = env_bool('HTTP_TRUST_ENV', False)

ICON_REFRESH_INTERVAL = env_int('ICON_REFRESH_INTERVAL', time_of_7_days, minimum=0)
ICON_CLIENT_CACHE_TIME = env_int('ICON_CLIENT_CACHE_TIME', time_of_7_days, minimum=0)
# -1 表示本地图标永久保留；非负值表示读取时按文件年龄淘汰。
ICON_FILE_EXPIRE_TIME = env_int('ICON_FILE_EXPIRE_TIME', -1, minimum=-1)
DEFAULT_CLIENT_CACHE_TIME = env_int('DEFAULT_CLIENT_CACHE_TIME', time_of_30_minus, minimum=0)
MEMORY_CACHE_MAX_ITEMS = env_int('MEMORY_CACHE_MAX_ITEMS', 5000, minimum=0)
MEMORY_CACHE_MAX_BYTES = env_int('MEMORY_CACHE_MAX_BYTES', 256 * 1024 * 1024, minimum=0)
MEMORY_CACHE_ITEM_MAX_BYTES = env_int('MEMORY_CACHE_ITEM_MAX_BYTES', 512 * 1024, minimum=0)
MEMORY_CACHE_RECHECK_INTERVAL = env_int('MEMORY_CACHE_RECHECK_INTERVAL', 60, minimum=0)
MAX_INFLIGHT_FETCHES = env_int('MAX_INFLIGHT_FETCHES', 500, minimum=1)
FOREGROUND_FETCH_TIMEOUT = env_float('FOREGROUND_FETCH_TIMEOUT', 10, minimum=0.001)
# 覆盖缓存 I/O、负缓存检查和前台抓取等待，避免反向代理先行超时。
FOREGROUND_RESPONSE_TIMEOUT = env_float('FOREGROUND_RESPONSE_TIMEOUT', 12, minimum=0.001)
DIRECT_FETCH_TIMEOUT = env_float('DIRECT_FETCH_TIMEOUT', 10, minimum=0.001)
FALLBACK_FETCH_TIMEOUT = env_float('FALLBACK_FETCH_TIMEOUT', 15, minimum=0.001)
FETCH_TOTAL_TIMEOUT = env_float('FETCH_TOTAL_TIMEOUT', 75, minimum=0.001)
REFRESH_QUEUE_MAX_SIZE = env_int('REFRESH_QUEUE_MAX_SIZE', 10000, minimum=1)
REFRESH_WORKERS = env_int('REFRESH_WORKERS', 16, minimum=1)

# 排行榜使用进程内计数，并通过当前服务启动批次下的有界快照跨 worker 聚合。
STATS_TOP_LIMIT = env_int('STATS_TOP_LIMIT', 10, minimum=1)
STATS_MAX_ITEMS = env_int('STATS_MAX_ITEMS', 50000, minimum=1)
STATS_SNAPSHOT_ITEMS = env_int('STATS_SNAPSHOT_ITEMS', 1000, minimum=1)
STATS_SNAPSHOT_INTERVAL = env_float('STATS_SNAPSHOT_INTERVAL', 3, minimum=0.001)
STATS_BOOT_ID = os.getenv('FAVICON_STATS_BOOT_ID', '').strip() or uuid.uuid4().hex
STATS_STARTED_AT = os.getenv('FAVICON_STATS_STARTED_AT', '').strip() or datetime.now(
    timezone.utc
).isoformat()

# 自定义协议映射。协议名使用小写且不包含 ://，目标必须是合法的 HTTP(S) URL。
CUSTOM_PROTOCOL_MAPPINGS = {
    'vscode': 'https://code.visualstudio.com',
    'jetbrains': 'https://www.jetbrains.com',
    'github': 'https://github.com',
}

# 图标获取接口配置
FAVICON_APIS = [
    ('https://t3.gstatic.cn/faviconV2?client=SOCIAL&fallback_opts=TYPE,SIZE,URL&type=FAVICON&size=128&url={base_url}',
     'gstatic接口'),
    ('https://favicon.im/{domain}', '第三方API'),
    ('', '网站默认位置/favicon.ico'),
]
