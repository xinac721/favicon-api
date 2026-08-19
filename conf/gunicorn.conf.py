# -*- coding: utf-8 -*-

from pathlib import Path

import yaml

# 绑定地址和端口
bind = "0.0.0.0:8000"

# Worker 进程数（推荐 CPU 核心数 * 2 + 1）
workers = 2

# 工作模式（sync、gevent、uvicorn.workers.UvicornWorker）
worker_class = "uvicorn_worker.UvicornWorker"

# 日志目录
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# 允许来自这些IP的代理转发
forwarded_allow_ips = "*"

# 日志配置
with open(Path(__file__).with_name("logging.yaml"), "r", encoding="utf-8") as f:
    logconfig_dict = yaml.safe_load(f)

# 日志级别（debug、info、warning、error）；以 YAML 配置优先
loglevel = "info"
# 访问日志文件（"-" 表示输出到 stdout）；以 YAML 配置优先
accesslog = "logs/access.log"
# 错误日志文件；以 YAML 配置优先
errorlog = "-"

# access_log_format 仅在 同步 worker 下有效，UvicornWorker下不可用；以 YAML 配置优先
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
raw_env = [
    "UVICORN_ACCESS_LOGFORMAT=%(h)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\" %(D)s"
]

# 超时时间（秒）
timeout = 120

# Keep-Alive超时
keepalive = 5
