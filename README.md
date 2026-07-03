# ingress_viz — Ingress Data Visualizer

Ingress 游戏数据可视化分析工具。ZIP + 密码存储在浏览器 IndexedDB 中；解析只在服务器内存中进行，不写入服务器磁盘。

## 运行

```bash
cd ingress_viz
source .venv/bin/activate
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

首次使用：上传 `.zip` 导出文件 + 输入密码 → 自动存入浏览器。再次打开直接点 Load。

## 停止

```bash
pkill -f "streamlit run app.py"
```

## 环境初始化

```bash
cd ingress_viz
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 调试

| 场景 | 方法 |
|------|------|
| 页面报错 | F12 → Console → 看 JS 错误和 `[IDB]` 日志 |
| 后端报错 | 终端 streamlit 输出即 log |
| Python 异常 | 直接打印在终端 + 页面红色框 |
| v2 组件不渲染/不触发 | Console 看是否有 `setTriggerValue` 错误 |
| Map 不显示内容 | 检查 Time range、Visualization、浏览器 Console 里的 WebGL/地图瓦片错误 |
| Map 性能问题 | 降低 Max cells / Max dots，关闭 Portal history overlay |
| IndexedDB 数据检查 | F12 → Application → IndexedDB → `ingress_viz2` → `sources` |

## 文件结构

```
ingress_viz/
├── app.py              # 入口：st.components.v2 管理 IndexedDB + st.navigation()
├── data_loader.py      # 100+ TSV/CSV 解析 → DataFrame dict
├── badge_config.py     # 牌子名称、文件映射、等级阈值
├── views/
│   ├── 1_Overview.py   # KPI 卡片、每日活动趋势、行为构成、AP 增长
│   ├── 2_Map.py        # PyDeck/WebGL 三图层：Density Heat / Grid Cells / Dot Scatter，支持点击详情
│   ├── 3_Activity.py   # 周趋势、时段热力图、Session 时长分布
│   ├── 4_Badges.py     # 牌子进度条、距下级差距、Onyx 倍数
│   ├── 5_Economy.py    # C.O.R.E. 订阅区间、CMU 余额 + 消费构成
│   └── 6_Events.py     # 赛季积分、Anomaly 门户、Second Sunday
├── requirements.txt
└── .venv/              # uv 创建的虚拟环境
```

## 已知待修

- **Map 自适应网格**：当前手动滑块控制格大小（100m-10km）。计划改为按时间范围和视口自动推荐 cell size。

## 技术栈

- Streamlit 1.58（MPA 模式 + `st.components.v2`）
- PyDeck/WebGL + CARTO basemap（地图）
- Plotly（图表）
- Pandas + NumPy（数据处理）
- pyzipper（AES 加密 ZIP 解密）
