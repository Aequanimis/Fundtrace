# FundTrace MVP Current Status

## 当前稳定版本

`v4-a2.1-stable` is the current MVP baseline. It keeps the A2.1 legacy model path; Phase B disclosure and equity-cap work remains Research only.

## MVP UI V1.1

- React + FastAPI local UI is complete; production serves the committed `frontend/dist` build on `127.0.0.1`.
- Production dependencies are pinned in `requirements-lock.txt` and verified in a clean Windows venv.
- The accepted A2.1 output is frozen at `tests/baseline/v4_a2_1_production/` with an exact regression command.
- Existing model A/B/C/D credibility is read from `report.md`; the UI does not invent a new grade.

## 性能（161005 基准）

- 快速分析：13.791 秒
- 完整 160 组标定：228.330 秒
- 标定 watchdog：300 秒硬上限

## 模型

- 周频隐含行业暴露，申万一级行业因子
- Lasso / constrained rolling regression
- recency weighting、anchor、noise band 与既有 A/B/C/D 可信度逻辑
- 输出是**隐含收益暴露**，不是实时真实持仓

`best_params_phaseA_candidate.json` 仅为 Research candidate，保持 `production_eligible=false`，不作为生产默认参数。

## 当前已知研究限制

1. holdings 披露覆盖度存在季度差异。
2. equity cap 仍使用 MVP legacy 逻辑。
3. 部分低 Σβ 不等同于实际低股票仓位。
4. Ground Truth 口径仍有优化空间。
5. 港股与 stock-level 路径尚未完整验证。

这些限制不阻塞 MVP 使用或下一阶段多基金测试。
