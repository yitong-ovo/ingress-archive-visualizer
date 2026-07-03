# Ingress Data Visualizer

本应用用于解析和浏览 Ingress GDPR 数据导出。它把导出 ZIP 中的 TSV、CSV、TXT 文件解析成内存里的 `pandas.DataFrame`，再通过 Streamlit 页面展示账号概览、地图活动、徽章、事件、经济记录、game log 和历史回顾。

ZIP 文件和解密密码保存在浏览器 IndexedDB 中；服务端解析只在内存中进行，不把解密后的导出写入磁盘。

## 运行

在仓库目录中执行：

```bash
source .venv/bin/activate
streamlit run app.py
```

浏览器打开：

```text
http://localhost:8501
```

首次使用时上传 Ingress 导出的 `.zip` 文件并输入密码。保存后再次打开页面，可以直接从浏览器本地存储中加载。

## 初始化环境

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 停止服务

```bash
pkill -f "streamlit run app.py"
```

## 页面

- `Overview`：账号指标、每日活动、行为构成、估算 AP 曲线。
- `Map`：活动点、密度格、Portal history overlay，并支持点击查看附近 Portal 和详情。
- `Activity`：周趋势、小时 x 星期热力图、登录 session 时长。
- `Badges`：徽章进度、下一档阈值、Onyx 倍数。
- `Economy`：CORE 订阅、CMU 余额、交易记录。
- `Events`：赛季积分、Anomaly portal interaction、Second Sunday 等活动记录。
- `Game Log`：game_log 行为、session、comm、稀有道具、reward、RPC、数据质量。
- `History`：面向历史回顾的通用解读，包括生命周期、玩法画像、纪录、地理旅程、Portal/POI、Link/Field、Machina、事件、经济和数据质量。

## 时区

侧边栏提供 `Display timezone` 设置。涉及日期、小时、星期、session 显示和历史回顾的页面会把 UTC 时间转换到所选时区后再聚合，避免凌晨/日期错位。

## 数据加载流程

`data_loader.py` 是数据入口，提供两个公开函数：

- `parse_archive(files, source_id)`：解析浏览器上传并解密后的 ZIP 成员，输入是 `{filename: bytes}`。
- `parse_directory(dir_path, source_id)`：解析已经解压到本地的导出目录，方便本地开发和调试。

解析结果是一个 `dict[str, DataFrame]`。例如：

- `hacks`
- `deploys`
- `game_log`
- `portal_history`
- `player_journey_actions`
- `_profile`

页面层只依赖这些标准 key，不直接读取原始文件。

## 调试

| 场景 | 方法 |
| --- | --- |
| 页面报错 | 浏览器 F12 → Console，看组件或地图错误 |
| 后端报错 | 查看运行 `streamlit run app.py` 的终端输出 |
| ZIP 加载失败 | 确认导出密码、ZIP 是否完整，以及浏览器 IndexedDB 中是否有旧缓存 |
| IndexedDB 检查 | F12 → Application → IndexedDB → `ingress_viz2` → `sources` |
| 地图不显示 | 检查时间范围、地图图层选择、浏览器 WebGL/网络错误 |
| 地图卡顿 | 降低 Max dots、Max cells 或关闭 Portal history overlay |
| History 地理视图不准 | 调整 `Place clustering granularity`；较小值适合社区/街区，较大值适合城市/旅行回顾 |

## 主要文件

```text
app.py                Streamlit 入口、IndexedDB 组件、页面导航
data_loader.py        GDPR 导出解析器
time_utils.py         显示时区工具
badge_config.py       徽章定义和阈值
views/                多页面视图
requirements.txt      Python 依赖
```

## 隐私与边界

- 解密后的导出数据只在服务端内存中解析。
- ZIP 和密码由浏览器 IndexedDB 保存，便于本地重复加载。
- 应用不会主动上传数据到外部服务。
- 地图底图来自 CARTO，浏览器会请求对应地图瓦片。

## 已知改进方向

- History 地理视图的地点命名仍基于经纬度簇，后续可接入离线地名或用户自定义别名。
- Map 的 cell size 仍由用户手动控制，后续可按视口和时间范围自动推荐。
- 大型 `game_log` 和 History 地理分析还有进一步缓存和预聚合空间。
