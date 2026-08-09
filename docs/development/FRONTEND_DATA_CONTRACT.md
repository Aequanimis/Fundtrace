# Frontend Data Contract

前端只负责调用后端并展示结果，不应重新实现量化模型。

## Input

- `fund_code`：6 位基金代码，例如 `161005`。
- 本地数据：`base/` 以及 `funds/<fund_code>/` 中的净值和持仓文件。

## Primary call

```bash
python run_analysis.py <fund_code>
```

当前 `app.py` 是本地 Streamlit 入口，可继续复用现有脚本调用方式；本阶段不提供 HTTP API。

## Result contract

运行完成后，从 `output/<fund_code>/` 读取：

- `report.md`：面向用户的文字解读。
- `positions.png`：主要仓位图。
- `weekly_positions.csv`：周频日期 × 行业的隐含暴露矩阵。
- `diagnostics.csv`：每期 `r2`、`sum_beta`、收敛状态及回归诊断。
- `sim_portfolio.csv`：季度模拟组合，用于模型解释与对账。

可能存在的 calibration 文件和 `best_params_phaseA_candidate.json` 属于研发/诊断产物；前端不得把 candidate 参数当作生产默认值。
