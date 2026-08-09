import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelStatus } from "./ResultsDashboard";

const diagnostics = {
  r2: 0.91,
  converged: true,
  model_version: "v4-a2.1-stable",
  parameters: { window: 120, half_life: 40, alpha: 1e-6 },
  data_cutoff: "2026-08-07",
};

describe("ModelStatus", () => {
  it.each([
    ["A", "可信"],
    ["B", "基本可信，局部谨慎"],
    ["C", "谨慎使用，多交叉验证"],
    ["D", "严重受限，仅作参考"],
  ])("renders the existing %s credibility grade", (grade, label) => {
    render(<ModelStatus credibility={{ grade, label }} diagnostics={diagnostics} analysisTime={15} />);
    expect(screen.getByText(`${grade} · ${label}`)).toBeInTheDocument();
  });

  it("uses a success icon when the latest window converged", () => {
    render(<ModelStatus credibility={null} diagnostics={diagnostics} analysisTime={15} />);
    expect(screen.getByTestId("convergence-ok-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("convergence-warning-icon")).not.toBeInTheDocument();
  });

  it("uses a warning icon when the latest window did not converge", () => {
    render(<ModelStatus credibility={null} diagnostics={{ ...diagnostics, converged: false }} analysisTime={15} />);
    expect(screen.getByTestId("convergence-warning-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("convergence-ok-icon")).not.toBeInTheDocument();
    expect(screen.getByText("最新窗口需关注")).toBeInTheDocument();
  });
});
