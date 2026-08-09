# FundTrace

**基金高频持仓追踪**

FundTrace 基于基金公开披露、复权净值和申万行业收益数据，估算主动权益基金在披露空窗期的周频隐含行业暴露与调仓方向。

> 输出是收益口径下的隐含暴露和估算仓位，不是基金实时真实持仓，仅供研究参考。

## 快速使用

Windows 用户双击 `启动基金高频分析.bat`，输入 6 位基金代码后选择“快速追踪”。第一次启动会自动创建本地 `.venv` 并安装依赖。

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

## 目录

- `lib/`：模型与回归实现
- `base/`：申万行业底座数据
- `funds/<代码>/`：基金输入数据
- `output/<代码>/`：运行输出
- `tests/baseline/161005/`：V3 固定回归基线
- `docs/development/`：迁移与性能研发记录

## 版本策略

- `v3-baseline`：迁移成功、尚未进行 V4 性能修改的冻结版本
- `feat/v4-performance-phase-a`：V4 Phase A 纯性能优化

V4 Phase A 不修改模型数学目标、参数网格、Ground Truth 或生产 solver。
