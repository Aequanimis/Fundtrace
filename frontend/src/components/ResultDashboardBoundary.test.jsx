import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultDashboardBoundary } from "./ResultDashboardBoundary";

function FailingResultSection() {
  throw new Error("simulated result section failure");
}

describe("ResultDashboardBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("replaces a result render failure with recovery actions", () => {
    const reset = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ResultDashboardBoundary onReset={reset}>
        <FailingResultSection />
      </ResultDashboardBoundary>,
    );

    expect(screen.getByTestId("result-dashboard-fallback")).toBeInTheDocument();
    expect(screen.getByText("结果页面显示失败")).toBeInTheDocument();
    expect(screen.getByText("错误编号：RESULT_DASHBOARD_RENDER_ERROR")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回首页" }));
    expect(reset).toHaveBeenCalledOnce();
  });
});
