#!/usr/bin/env sh

set -e

mkdir -p /app/conf

default_conf_dir="/app/conf.default"
gunicorn_conf="/app/conf/gunicorn.conf.py"
logging_conf="/app/conf/logging.yaml"

if [ ! -f "$gunicorn_conf" ]; then
    echo "复制 gunicorn.conf.py..."
    if [ -f "${default_conf_dir}/gunicorn_conf_py" ]; then
        cp "${default_conf_dir}/gunicorn_conf_py" "$gunicorn_conf"
        chmod 644 "$gunicorn_conf"
        echo "复制 gunicorn.conf.py 成功"
    else
        echo "警告：默认配置文件 ${default_conf_dir}/gunicorn_conf_py 不存在，创建空文件"
        touch "$gunicorn_conf"
        chmod 644 "$gunicorn_conf"
    fi
fi

if [ ! -f "$logging_conf" ]; then
    echo "复制 logging.yaml..."
    if [ -f "${default_conf_dir}/logging.yaml" ]; then
        cp "${default_conf_dir}/logging.yaml" "$logging_conf"
        chmod 644 "$logging_conf"
        echo "复制 logging.yaml 成功"
    else
        echo "警告：默认配置文件 ${default_conf_dir}/logging.yaml 不存在，创建空文件"
        touch "$logging_conf"
        chmod 644 "$logging_conf"
    fi
fi

if [ ! -d "/app/logs" ]; then
    mkdir -p /app/logs
    chmod 755 /app/logs
fi

if [ ! -d "/app/data" ]; then
    mkdir -p /app/data
    chmod 755 /app/data
fi

exec "$@"
