# favicon-api-v4

异步获取网站 favicon，并使用内存热缓存和磁盘持久缓存快速响应高频请求。

## v4版本发布
1. 本项目已更新到v4版本，优化了很多内容，大幅提升性能和稳定性（整体用codex重构了）
2. v4版本目前已上线docker仓库，源码后续提交，Usage: `docker pull xinac721/favicon-api`
3. 使用方式详见docker仓库介绍，v4版本自带静态页面
4. 本项目服务日均请求500W次，服务器和带宽有限，逐情使用，欢迎自建服务
5. 禁止用于非法网站的使用，本站接连收到警告，请自觉！！！


## Usage

- https://api.xinac.net/

```bash
python3 -m pip install -r requirements.txt
python3 run.py
```

- 启动方式：
  
1. 生产环境：

```bash
./startup.sh
```

2. Docker：

```bash
docker compose up -d
```

- API使用示例

  https://api.xinac.net/icon/?url=https://www.baidu.com
