# 110022 首次数据抓取诊断

## 结论

- 初始本地状态：`NO_LOCAL_DATA`。
- 失败阶段：`NAV`，具体发生在分红占位行参与复权净值解析时。
- 根因：东方财富分红页对 110022 返回一行“暂无分红信息!”。金额正则无法匹配后，旧代码执行 `np.nan`，但 `fetch_fund_manual.py` 未导入 `numpy as np`，因此抛出 `NameError`。
- 分类：`FUND_SPECIFIC_FETCH_FAILURE`。同一时间、同一锁定环境和同一数据源下，161005 的元数据、NAV、持仓与行业配置均成功；110022 的各公开接口本身也都可用。
- 数据源与依赖：未更换数据源，未修改 `requirements-lock.txt`。

## 复现结果

| 部分 | 数据源 / 函数 | 结果 | 记录与范围 | 说明 |
|---|---|---|---|---|
| 基金信息 | 东方财富 `pingzhongdata` / `fS_name` | SUCCESS | 易方达消费行业股票 | 六位代码 `110022` 直接可用，无需 `.OF` |
| NAV 原始数据 | 东方财富 `pingzhongdata` / `parse_nav` | SUCCESS | 3860 行，2010-08-20 至 2026-08-07 | 字段结构正常 |
| NAV 复权 | 东方财富分红页 / `add_adjusted_nav` | FAILED（修复前） | 分红占位行 1 行 | `NameError: name 'np' is not defined` |
| Holdings | AkShare `fund_portfolio_hold_em` | SUCCESS | 修复后 673 行、18 个报告期 | 2022Q1 至 2026Q2 |
| Industry Allocation | AkShare `fund_portfolio_industry_allocation_em` | SUCCESS | 修复后 117 行、18 个报告期 | 2022-03-31 至 2026-06-30 |
| Base Data | 本地 `base/` | SUCCESS | 31 个行业指数、5876 只股票映射 | 无需重新抓取 |

## 161005 同源对照

- 基金信息：SUCCESS，富国天惠成长混合(LOF)A。
- NAV：SUCCESS，5057 行，2005-11-16 至 2026-08-07。
- Holdings（2025）：SUCCESS，265 行。
- Industry Allocation（2025）：SUCCESS，60 行。
- 161005 有 16 条可解析分红；110022 返回“暂无分红信息!”占位行，因此只有 110022 触发旧代码的未匹配分支。

## 修复

- 未匹配的分红占位行现在被安全跳过，不再依赖未导入的 `np.nan`。
- NAV、持仓、行业配置和 manifest 均先验证，再使用同目录临时文件与 `os.replace` 原子替换。
- 空表、缺字段或某阶段失败会返回结构化 `stage`、`code`、`message`，并保留已有正式文件。
- 每次抓取写入 `logs/fetch_<fundcode>_<timestamp>.log`。
- API 将结构化抓取错误传给前端，普通用户看到阶段相关中文提示，详细异常只保留在日志中。
