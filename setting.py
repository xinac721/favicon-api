# -*- coding: utf-8 -*-

import os

from favicon_app.utils.file_util import FileUtil

# 获取当前所在目录
_current_dir = os.path.dirname(os.path.abspath(__file__))

# icon 存储的绝对路径
icon_root_path = _current_dir
# 站点的 favicon.ico 图标
favicon_icon_file = FileUtil.read_file(os.path.join(icon_root_path, 'favicon.ico'), mode='rb')
# 默认的站点图标
default_icon_path = os.path.join(icon_root_path, 'favicon.png')
default_icon_file = FileUtil.read_file(default_icon_path, mode='rb')
# 定义referer日志文件路径
referer_log_file = os.path.join(icon_root_path, 'data', 'referer.txt')
# 定义失败URL日志文件路径
# failed_urls_file = os.path.join(icon_root_path, 'data', 'failedurls.txt')
# 定义失败URL存储目录
failed_urls_dir = os.path.join(icon_root_path, 'data', 'failed_urls')

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

# 失败URL默认失效时间
FAILED_URL_EXPIRE_TIME = time_of_6_hours

# 图标获取接口配置
# 格式: (模板URL, 名称)
# 支持的变量: {domain} - 域名, {base_url} - 基础URL
FAVICON_APIS = [
    ('https://t3.gstatic.cn/faviconV2?client=SOCIAL&fallback_opts=TYPE,SIZE,URL&type=FAVICON&size=128&url={base_url}',
     'gstatic接口'),
    ('https://favicon.is/{domain}', '第三方API'),
    ('', '网站默认位置/favicon.ico'),
]
