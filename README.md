# 前沿大模型智能指数看板

追踪 [Artificial Analysis](https://artificialanalysis.ai/) 的 **Frontier Language Model Intelligence** 演进，
并分析前沿模型（智能指数 Top-3）的**迭代节奏**与**月度加速度**。

在线看板：`index.html`（GitHub Pages 从仓库根目录提供，双击本地打开亦可，无任何外部依赖）。

## 目录说明

| 文件 | 作用 |
| --- | --- |
| `aa_frontier_fetch.py` | 抓取首页 → 提取 RSC manifest → AES-256-GCM 解密 → 导出 CSV/JSON |
| `analyze_cadence.py` | 迭代节奏分析：去重复、模拟 Top-3 更替、三口径统计、月度加速度 |
| `build_dashboard.py` | 把数据注入 HTML 模板，生成 `aa_frontier_dashboard.html` 与 `index.html` |
| `aa_dashboard_template.html` | 看板模板（纯 SVG 图表，零外部依赖） |
| `aa_models.csv` | 全量模型指标（智能指数 + 18 项 benchmark + 价格） |
| `aa_frontier.csv` | 前沿台阶明细（刷新历史最高分的模型） |
| `aa_frontier_by_creator.csv` | 各厂商自身的 frontier 曲线 |
| `aa_cadence.json` | 迭代节奏数据（三口径 + 在榜时长 + 月度） |
| `aa_frontier.json` | 看板使用的精简数据 |

## 快速开始

```bash
pip install cryptography

python aa_frontier_fetch.py      # 抓取 + 解密 + 导出
python analyze_cadence.py        # 迭代节奏分析
python build_dashboard.py        # 生成看板
```

然后打开 `aa_frontier_dashboard.html`（或 `index.html`）。

## 数据获取原理

站点把全量数据放在 `/data/<hash>.txt`，使用 **AES-256-GCM** 加密 + gzip 压缩。
密钥清单（manifest）内嵌在页面的 Next.js RSC payload 中：

```json
{"path":"/data/2a1c2b25faec2404.txt","key":"<64 位 hex>"}
```

解密参数（逆向自 JS chunk `static_chunks/24153-*.js`）：

```
key = bytes.fromhex(manifest.key)        # 32 字节
iv  = SHA256(key).digest()[:12]
明文 = AESGCM(key).decrypt(iv, blob, None)
JSON = gzip.decompress(明文)
```

**key 每次部署都会轮换**，因此脚本从页面动态提取 manifest，无需维护任何凭据。

## 三种迭代口径

| 口径 | 定义 |
| --- | --- |
| **A · 厂商版本迭代**（主） | 同一厂商连续两次发布「进入 Top-3 的新版本」的日期差 |
| **B · Top-3 席位更替** | Top-3 阵容发生变化的相邻日期差 |
| **C · 榜首易主** | 第 1 名换人的相邻日期差 |

配套指标**在榜时长**：模型进入 Top-3 后被挤出的天数。

> 注：AA 把同一模型的不同 reasoning effort（xhigh/high/medium/low）记为独立模型且同日发布，
> 直接计算会产生大量 0 天间隔。分析前先按 `(厂商, 去括号系列名, 发布日期)` 合并。

## 月度视图

`analyze_cadence.py` 中的 `START_MONTH`（默认 `2026-01`）控制月度分析起点。
月度样本稀疏（每月 0~3 次），因此同时提供：

- `roll3` —— 滚动 3 个月中位间隔（平滑趋势，主看这根线）
- `frontierDelta` —— 每月前沿指数增量（每月都有值，可与迭代频率互补）

## 自动更新

每周一自动执行三步脚本并提交（见仓库的 GitHub Actions / 定时任务配置）。
数据来自 Artificial Analysis，指标口径以其官方定义为准。
