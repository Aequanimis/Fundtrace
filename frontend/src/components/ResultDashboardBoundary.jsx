import { Component } from "react";

export class ResultDashboardBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    // Keep the useful diagnostic in DevTools without exposing a stack trace in the UI.
    console.error("[FundTrace] Result dashboard render failed", error, info);
  }

  reload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <main className="results-dashboard relative z-20 grid min-h-screen place-items-center bg-black px-6 text-white">
        <section className="result-card max-w-lg p-6 text-center" aria-live="assertive" data-testid="result-dashboard-fallback">
          <p className="text-base text-zinc-100">结果页面显示失败</p>
          <p className="mt-3 text-sm leading-6 text-zinc-400">分析结果已经保存，可尝试重新加载结果。</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <button type="button" className="primary-small" onClick={this.reload}>重新加载结果</button>
            <button type="button" className="secondary-button" onClick={this.props.onReset}>返回首页</button>
          </div>
          <p className="mt-5 text-xs text-zinc-600">错误编号：RESULT_DASHBOARD_RENDER_ERROR</p>
        </section>
      </main>
    );
  }
}
