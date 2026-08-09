# Equity Cap Findings

Research B2 发现 legacy holdings-based equity cap 会在部分时期压制模型：TYPE_A=120、TYPE_B=6、TYPE_C=0、TYPE_D=918。

诊断结论为 `B2_CHANGE_MOSTLY_EXPLAINED_BY_CAP_RELEASE`，但 disclosure-cap 实验使 Top5 一致率降至 91.28%，会改变历史行业暴露。因此它不自动进入 MVP；A2.1 legacy 继续作为当前 MVP 模型。
