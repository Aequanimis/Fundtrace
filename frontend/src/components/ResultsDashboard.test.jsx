import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  FONT_SCALES,
  ModelStatus,
  ResultsDashboard,
  TREND_COLORS,
  normalizeDashboardData,
  persistFontScale,
  readFontScale,
  resolveSelectedColors,
} from "./ResultsDashboard";

const diagnostics = {
  r2: 0.91,
  converged: true,
  model_version: "v4-a2.1-stable",
  parameters: { window: 120, half_life: 40, alpha: 1e-6 },
  data_cutoff: "2026-08-07",
};

const validResults = {
  fund_code: "110022",
  latest_date: "2026-08-07",
  analysis_time: 8.4,
  summary: {
    sentence: "测试摘要",
    main_industry: { industry: "食品饮料", exposure: 0.6 },
    largest_increase: { industry: "食品饮料", delta: 0.08 },
    largest_decrease: { industry: "汽车", delta: -0.05 },
    implicit_exposure_sum: 0.94,
  },
  top_industries: [
    { industry: "食品饮料", exposure: 0.6 },
    { industry: "汽车", exposure: 0.2 },
  ],
  all_industries: [
    { industry: "食品饮料", exposure: 0.6 },
    { industry: "汽车", exposure: 0.2 },
  ],
  four_week_changes: {
    from_date: "2026-07-10",
    to_date: "2026-08-07",
    increases: [{ industry: "食品饮料", delta: 0.08 }],
    decreases: [{ industry: "汽车", delta: -0.05 }],
  },
  trend: [
    { date: "2026-07-10", values: { 食品饮料: 0.52, 汽车: 0.25 } },
    { date: "2026-08-07", values: { 食品饮料: 0.6, 汽车: 0.2 } },
  ],
  disclosure_comparison: [],
  credibility: { grade: "A", label: "可信" },
  diagnostics,
  downloads: [],
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

describe("dashboard presentation preferences", () => {
  it("defaults to 115% and restores a supported local setting", () => {
    expect(FONT_SCALES).toEqual([90, 100, 115, 130]);
    expect(readFontScale({ getItem: () => null })).toBe(115);
    expect(readFontScale({ getItem: () => "130" })).toBe(130);
    expect(readFontScale({ getItem: () => "123" })).toBe(115);
    expect(readFontScale({ getItem: () => "not-a-size" })).toBe(115);
    expect(readFontScale({ getItem: () => { throw new Error("storage disabled"); } })).toBe(115);
  });

  it("persists the selected scale with the stable storage key", () => {
    const setItem = vi.fn();
    persistFontScale({ setItem }, 90);
    expect(setItem).toHaveBeenCalledWith("fundtrace-font-scale", "90");
  });

  it("keeps up to eight selected series distinct and deterministic", () => {
    const selected = ["电子", "交通运输", "计算机", "食品饮料", "国防军工", "汽车"];
    const preferred = Object.fromEntries(selected.map((industry, index) => [industry, TREND_COLORS[index % 3]]));
    const first = resolveSelectedColors(selected, preferred);
    const second = resolveSelectedColors(selected, preferred);
    expect(new Set(Object.values(first))).toHaveLength(selected.length);
    expect(first).toEqual(second);
    expect(first["电子"]).toBe(preferred["电子"]);
    expect(resolveSelectedColors(["未知行业"], {})).toEqual({ 未知行业: TREND_COLORS[0] });
  });
});

describe("ResultsDashboard defensive rendering", () => {
  it("renders a valid result immediately without waiting for an animation event", () => {
    render(<ResultsDashboard data={validResults} onReset={vi.fn()} onAnalyze={vi.fn()} />);
    expect(screen.getByRole("main")).toHaveClass("results-dashboard", "results-enter");
    expect(screen.getByText("本次追踪")).toBeInTheDocument();
    expect(screen.getByText("当前隐含行业暴露")).toBeInTheDocument();
  });

  it("shows a trend fallback rather than crashing on empty trend data", () => {
    render(<ResultsDashboard data={{ ...validResults, trend: [] }} onReset={vi.fn()} onAnalyze={vi.fn()} />);
    expect(screen.getByText("暂无趋势数据")).toBeInTheDocument();
    expect(screen.getByText("模型状态")).toBeInTheDocument();
  });

  it("renders safely when credibility and optional result sections are missing", () => {
    render(<ResultsDashboard data={{ ...validResults, credibility: null, disclosure_comparison: null, downloads: null }} onReset={vi.fn()} onAnalyze={vi.fn()} />);
    expect(screen.getByText("当前隐含行业暴露")).toBeInTheDocument();
    expect(screen.queryByLabelText(/可信度/)).not.toBeInTheDocument();
  });

  it("normalizes invalid chart values before Recharts receives them", () => {
    const normalized = normalizeDashboardData({
      ...validResults,
      trend: [{ date: "2026-08-07", values: { 食品饮料: "NaN", 汽车: Infinity } }],
    });
    expect(normalized.trend[0].values).toEqual({ 食品饮料: null, 汽车: null });
  });
});
