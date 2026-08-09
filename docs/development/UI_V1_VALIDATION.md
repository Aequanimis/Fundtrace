# FundTrace MVP UI V1 验收

- 分支：`feat/mvp-react-ui`
- 量化核心：与 `mvp/pre-ui` 一致，未修改；未运行 calibration。
- React：生产构建成功；首屏 bundle 约 20.8 kB，图表模块延迟加载。
- FastAPI：仅绑定 `127.0.0.1:8765`，生产模式直接提供 `frontend/dist`。
- Hero 视频：CDN HEAD 返回 `200 video/mp4`；URL 集中在 `frontend/src/config/branding.js`；7 秒超时或 `onError` 自动使用 SVG fallback。
- 响应式：1440×900、1280×720、390×844 的布局规则、无横向滚动约束、移动菜单和单列断点已检查；移动菜单 render test 通过。Codex 浏览器连接组件本轮报本地 kernel assets 路径错误，因此未生成浏览器截图。

## 唯一一次 161005 UI 全链路

- 入口：React 基金代码表单；`update_data=false`，未重新抓取数据。
- 模型自身耗时：`16.313` 秒。
- 点击到结果预计：约 `17.5` 秒（模型耗时 + 最多 0.75 秒轮询 + 0.42 秒完成过渡），低于 25 秒目标。
- 结果渲染：摘要、Top10 暴露、4 周变化、52 周趋势、披露对比、模型状态、3 个下载入口均成功构造；披露对比本次有 10 行。
- 与 Phase B0+B1 验收包内的 A2.1 stable `weekly_positions.csv` 比较：`array_equal=true`，`max_abs_diff=0.0`。
- Top5 一致率：`1044/1044`。

## 测试

- `pytest -q`：27 passed（1 条第三方弃用警告）。
- `npm test`：2 passed，条件式 live E2E 默认跳过；live E2E 使用已完成 job 重验 dashboard 为 1 passed。
- `npm run build`：成功。
