# favicon-api-v3

### 接口简介

- https://api.xinac.net/

### 接口演示

- https://api.xinac.net/icon/

### 使用方式

1. python3 -m pip install -r requirements.txt
2. python3 run.py

### 生产使用

1. python3 -m pip install -r requirements.txt
2. chmod +x startup.sh && ./startup.sh

> 生产环境使用仅支持Linux或Docker运行

### docker运行

1. docker pull xinac721/favicon-api
2. docker compose up -d

> 自行构建：docker build -t favicon-api:latest .

### API使用

  https://api.xinac.net/icon/?url=https://www.baidu.com
