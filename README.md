# Ingress GDPR 数据本地解读工具

这是一个本地运行的 Streamlit 应用，用于解析 Ingress GDPR 数据导出，并把长期游戏记录整理成可浏览的视图：账号概览、活动地图、时间趋势、徽章、事件、经济记录、game log 和历史回顾。

文档刻意不绑定仓库名。只要目录里保留同样的 Python 文件和 `views/` 页面，项目目录名称以后可以更换。

## 适用场景

- 回顾多年行为画像、峰值日、活动参与、Portal/POI 生命周期和地理旅程。
- 检查 game log、登录 session、商店记录、Wayfarer/POI 提交等导出数据。
- 在本机完成解密、解析和可视化，不把原始导出主动上传到外部服务。

## 数据与隐私

- 浏览器端保存上传的 ZIP 和解密密码，便于下次打开时复用。
- 服务端只在内存中解析解密后的数据，不会把解密内容写入项目目录。
- 地图底图使用 CARTO，浏览器会向地图瓦片服务请求底图资源。
- 页面中的所有统计都基于当前上传或本地解析的数据源。

## 初始化环境

在项目目录中执行：

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

如果已经存在 `.venv`，通常只需要：

```bash
source .venv/bin/activate
```

## 运行

```bash
streamlit run app.py
```

默认地址：

```text
http://localhost:8501
```

首次使用时上传 Ingress 导出的加密 `.zip` 文件并输入密码。保存后再次打开页面，可以直接从浏览器本地存储中加载。

## 停止服务

```bash
pkill -f "streamlit run app.py"
```

## 页面结构

| 页面 | 作用 |
| --- | --- |
| `Overview` | 账号指标、每日活动、行为构成、估算 AP 曲线。 |
| `Map` | 活动点、密度格、Portal history overlay、附近 Portal 详情。 |
| `Activity` | 周趋势、小时 x 星期热力图、登录 session 时长。 |
| `Badges` | 徽章进度、下一档阈值、Onyx 倍数。 |
| `Economy` | CORE 订阅、CMU 余额、商店和 passcode 记录。 |
| `Events` | 赛季积分、Anomaly interaction、Second Sunday、Mission Day 等活动记录。 |
| `Game Log` | game_log 行为、session、comm、稀有道具、reward、RPC、数据质量。 |
| `History` | 面向历史回顾的通用解读：玩法画像、纪录、地理旅程、Portal/POI、Link/Field、Machina、事件和经济。 |

## 时区

原始导出中的时间按 UTC 解析。侧边栏的 `Display timezone` 控制页面展示和聚合时使用的本地时区，影响日期、小时、星期、session 和历史回顾统计。

如果看到行为集中在凌晨，优先检查这里的时区设置。

## 数据加载流程

`data_loader.py` 是应用的数据入口。页面不直接读取原始 TSV/CSV/TXT 文件，而是读取它输出的标准化 `dict[str, pandas.DataFrame]`。

公开入口：

- `parse_archive(files, source_id)`：解析浏览器上传并解密后的 ZIP 成员，输入是 `{filename: bytes}`。
- `parse_directory(dir_path, source_id)`：解析已经解压到本地的导出目录，主要用于本地开发、调试和性能测试。

常见输出 key：

- `game_log`
- `portal_history`
- `GameplayLocationHistory`
- `Logins`
- `hacks`
- `deploys`
- `links_created`
- `regions_created`
- `poi_submissions`
- `player_journey_actions`
- `_profile`

所有时间列在加载阶段统一解析为 UTC；本地时区转换放在页面层和 `time_utils.py` 中处理。

## 主要文件

```text
app.py              Streamlit 入口、数据源选择、IndexedDB 组件、页面导航
data_loader.py      Ingress GDPR 导出解析器
time_utils.py       展示时区选择与时间转换工具
badge_config.py     徽章定义和阈值
views/              多页面视图
requirements.txt    Python 依赖
```

## 本地调试

| 问题 | 检查方式 |
| --- | --- |
| 页面报错 | 浏览器 F12 -> Console，看前端组件或地图错误。 |
| 后端报错 | 查看运行 `streamlit run app.py` 的终端输出。 |
| ZIP 加载失败 | 确认导出密码、ZIP 完整性，以及浏览器 IndexedDB 中是否有旧缓存。 |
| 地图不显示 | 检查时间范围、地图图层、浏览器 WebGL 和网络请求。 |
| 地图卡顿 | 降低 Max dots、Max cells，或关闭 Portal history overlay。 |
| History 地理视图不准 | 调整 `Place clustering granularity`；小粒度适合社区/街区，大粒度适合城市/旅行回顾。 |

## 已知改进方向

- `game_log.tsv` 数据量大时加载仍是主要耗时来源，可以继续优化解析和缓存。
- History 地理视图目前以坐标聚类为主，后续可以支持用户自定义地点别名或离线地名。
- 地图层参数仍偏手动，后续可以根据视口、数据量和时间范围自动推荐。
