# -*- coding: utf-8 -*-

from pathlib import Path
import os
import uuid
from datetime import datetime, timezone

import yaml

from favicon_app.utils.env import env_int

# 绑定地址和端口
bind = "0.0.0.0:8000"

# Worker 进程数（推荐 CPU 核心数 * 2 + 1）
workers = env_int("WEB_CONCURRENCY", 2, minimum=1)

# 工作模式（sync、gevent、uvicorn.workers.UvicornWorker）
worker_class = "uvicorn_worker.UvicornWorker"

# 日志目录
project_root = Path(__file__).resolve().parent.parent
log_dir = project_root / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# 默认信任回环地址和 RFC 1918 私网中的反向代理；可通过环境变量覆盖。
default_forwarded_allow_ips = ",".join((
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1",
))
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", default_forwarded_allow_ips)

# Gunicorn 26 默认启用本地管理 socket；本服务不暴露该管理面。
control_socket_disable = True

# 日志配置
with open(Path(__file__).with_name("logging.yaml"), "r", encoding="utf-8") as f:
    logconfig_dict = yaml.safe_load(f)
for handler in logconfig_dict.get("handlers", {}).values():
    filename = handler.get("filename")
    if filename and not Path(filename).is_absolute():
        handler["filename"] = str(project_root / filename)

# 日志级别（debug、info、warning、error）；以 YAML 配置优先
loglevel = "info"
# 访问日志文件（"-" 表示输出到 stdout）；以 YAML 配置优先
accesslog = None
# 错误日志文件；以 YAML 配置优先
errorlog = "-"

# access_log_format 仅在 同步 worker 下有效，UvicornWorker下不可用；以 YAML 配置优先
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
stats_boot_id = os.getenv("FAVICON_STATS_BOOT_ID") or uuid.uuid4().hex
stats_started_at = os.getenv("FAVICON_STATS_STARTED_AT") or datetime.now(timezone.utc).isoformat()
raw_env = [
    "UVICORN_ACCESS_LOGFORMAT=%(h)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\" %(D)s",
    f"FAVICON_STATS_BOOT_ID={stats_boot_id}",
    f"FAVICON_STATS_STARTED_AT={stats_started_at}",
]

# 超时时间（秒）
timeout = 120

# Keep-Alive超时
keepalive = 5

# 定期回收 worker，防止长期运行进程因第三方库缓存累积。
max_requests = env_int("MAX_REQUESTS", 200000, minimum=0)
max_requests_jitter = env_int("MAX_REQUESTS_JITTER", 10000, minimum=0)
