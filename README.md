# api_favicon

- https://api.xinac.net/

`python3 -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

- 启动方式：
  
  python3 main.py 或 uwsgi --ini uwsgi.ini

- API使用

  https://api.xinac.net/icon/?url=https://www.baidu.com

- Notice

  此版本为同步模式运行版本，异步模式版本后续逐情发布。区别如下：

  同步模式：接收到请求后一个一个的依次顺序处理，用户首次使用可能会等待一些时间。好处是获取到的图标可以立即响应。

  异步模式：前五个请求按顺序处理，之后的请求用线程后台处理。此时用户首次使用一般只能正确返回五个图标，其他的都为默认图标。

  相同点：图标获取完成后，再次请求效果都是一样的，所以刷新几次就都一样了。

- LICENSE

  Apache License 2.0

  欢迎参与贡献代码，使用本代码请添加说明或友情链接。

- **请注意**

  1. 本站日均请求量30W+，使用本站服务的网站1000+，严禁用于非法网站！
  2. 由于非法使用，本站已被云厂商数次警告，几近关停，请合法使用！
  3. 本站目前非盈利，尽力运营，时间未知，欢迎自建。
  4. 欢迎提交PR，欢迎赞助。
 
## v4版本发布
1. 本项目已更新到v4版本，优化了很多内容，大幅提升性能和稳定性（整体用codex重构了）
2. v4版本目前已上线docker仓库，源码后续提交，Usage: `docker pull xinac721/favicon-api`
3. 使用方式详见docker仓库介绍，v4版本自带静态页面
4. 本项目服务日均请求500W次，服务器和带宽有限，逐情使用，欢迎自建服务
5. 禁止用于非法网站的使用，本站接连收到警告，请自觉！！！
