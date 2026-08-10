# FundTrace

**基金高频持仓追踪**

FundTrace 基于基金公开披露、复权净值和申万行业收益数据，估算主动权益基金在披露空窗期的周频隐含行业暴露与调仓方向。

> 输出是收益口径下的隐含暴露和估算仓位，不是基金实时真实持仓，仅供研究参考。

## 快速使用

Windows 用户双击 `启动FundTrace.bat`，浏览器会自动打开全新的本地 FundTrace 界面。第一次启动会自动创建本地 `.venv` 并安装 Python 依赖；发布包已包含 `frontend/dist`，最终用户不需要安装 Node.js。

正常流程：输入基金代码 → 更新或读取已有数据 → 快速分析 → 查看 Dashboard。

- 使用本地已有数据的快速分析约 15 秒。
- 更新公开数据再分析的总耗时取决于网络和数据源响应，不包含在“约 15 秒”内。

旧版 Streamlit 界面仍可通过 `启动基金高频分析.bat` 使用。

命令行快速分析：

```bash
python run_analysis.py 161005
```

高级完整标定需显式选择 GUI 的“重新标定模型”或执行：

```bash
python run_analysis.py 161005 --calibrate
```

完整标定在独立 worker 中运行：285 秒安全停止、300 秒硬 watchdog，逐组合原子保存 checkpoint。Phase A 只生成候选参数，不会替换正式参数或改变当次快速分析结果。

数据抓取、模型口径、结果解读和 V3 已知局限详见 [README_V3.md](README_V3.md) 与 [SKILL.md](SKILL.md)。

## 当前功能

- 从公开持仓披露、基金复权净值和申万行业收益数据估算周频隐含行业暴露。
- 展示披露空窗期可能的行业调仓方向、拟合质量和约束诊断。
- 提供 React + FastAPI 本地界面，并保留 Streamlit 与命令行使用方式。

## 输出说明

运行后在 `output/<代码>/` 查看：

- `report.md`：文字解读
- `positions.png`：主要行业暴露图
- `weekly_positions.csv`：周频行业暴露
- `diagnostics.csv`：R²、Σβ 与收敛诊断
- `sim_portfolio.csv`：季度模拟组合

## 模型限制

FundTrace 给出的是**隐含收益暴露**，不是实时真实持仓。披露覆盖度、权益上限口径、Ground Truth、港股和 stock-level 路径仍有研究空间；这些限制不阻塞当前 MVP 使用。

## Development Status

- **MVP UI V1.1**：React/FastAPI 本地产品界面可用，正在完成 release stabilization；下一步为多基金 MVP 测试。
- **Research**：disclosure coverage 与 equity-cap 实验独立保留，不自动覆盖 MVP。
- Phase A candidate 参数保持 `production_eligible=false`，不会作为默认生产参数。

生产依赖精确版本保存在 `requirements-lock.txt`。`启动FundTrace.bat` 只有在依赖缺失或版本不匹配时才安装该 lock，不会每次启动都重新解析或升级依赖。更新依赖前必须运行：

```bash
python tools/check_production_regression.py 161005
```

## 目录

- `lib/`：模型与回归实现
- `api/`：仅绑定 `127.0.0.1` 的本地 API 桥接
- `frontend/src/`：React 界面源码
- `frontend/dist/`：无需 Node.js 即可运行的生产构建
- `base/`：申万行业底座数据
- `funds/<代码>/`：基金输入数据
- `output/<代码>/`：运行输出
- `tests/baseline/161005/`：V3 固定回归基线
- `tests/baseline/v4_a2_1_production/`：A2.1 生产回归基线
- `docs/development/`：迁移与性能研发记录

## 版本策略

- `v3-baseline`：迁移成功、尚未进行 V4 性能修改的冻结版本
- `v4-a2.1-stable`：当前 MVP 稳定基线
- Research branches：披露和 equity-cap 实验资产，不合并进 MVP

更多状态见 [MVP_STATUS.md](docs/development/MVP_STATUS.md)、[VERSION_HISTORY.md](docs/development/VERSION_HISTORY.md) 和 [RESEARCH_BACKLOG.md](docs/research/RESEARCH_BACKLOG.md)。

## Windows 便携版

面向普通用户的发布物为 GitHub Release 中的 `FundTrace_Windows_Portable_V1.2.zip`。完整解压后双击 `启动FundTrace.bat` 即可使用，不需要安装 Python、Node.js、pip 或配置 PATH。源码仓库仍使用开发版启动器和 `.venv`；便携包的构建与验收规则见 [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md)。
