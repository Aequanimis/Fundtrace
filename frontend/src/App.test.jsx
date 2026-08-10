import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("FundTrace UI", () => {
  it("shows the connected backend build without exposing local paths", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok",
      app: "FundTrace",
      git_commit: "1ccbb8f4412bb4881230412172ccf4283b903872",
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    render(<App />);

    expect(await screen.findByLabelText("FundTrace build"))
      .toHaveTextContent("FundTrace v1.2 · Build 1ccbb8f");
  });

  it("renders the cinematic hero and fund-code entry", () => {
    render(<App />);
    expect(screen.getByText("看见披露空窗期里的变化")).toBeInTheDocument();
    expect(screen.getByLabelText("基金代码")).toHaveAttribute("placeholder", "输入6位基金代码，例如 161005");
    expect(screen.getByRole("button", { name: /开始分析/ })).toBeInTheDocument();
  });

  it("validates fund codes and opens the compact menu", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("基金代码"), { target: { value: "161" } });
    fireEvent.click(screen.getByRole("button", { name: /开始分析/ }));
    expect(screen.getByText("请输入6位基金代码")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开菜单" }));
    expect(screen.getByRole("button", { name: "关闭菜单" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "趋势" })).toHaveLength(2);
  });

  it("shows a useful local-service message for network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<App />);

    fireEvent.change(screen.getByLabelText("基金代码"), { target: { value: "161005" } });
    fireEvent.click(screen.getByRole("button", { name: /开始分析/ }));

    expect(await screen.findByText("无法连接本地分析服务，请确认FundTrace仍在运行。"))
      .toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("shows HTTP status instead of a generic fetch failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "测试请求无效",
    }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    })));
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      detail: "\u6d4b\u8bd5\u8bf7\u6c42\u65e0\u6548",
    }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    }))));
    render(<App />);

    fireEvent.change(screen.getByLabelText("基金代码"), { target: { value: "161005" } });
    fireEvent.click(screen.getByRole("button", { name: /开始分析/ }));

    expect(await screen.findByText("分析请求失败（HTTP 422）：测试请求无效"))
      .toBeInTheDocument();
  });

  it("opens a saved result directly after a refresh without rerunning the model", async () => {
    window.history.replaceState(null, "", "/?result=110022");
    const result = {
      fund_code: "110022",
      latest_date: "2026-08-07",
      summary: {
        sentence: "已保存结果",
        main_industry: { industry: "食品饮料", exposure: 0.6 },
        largest_increase: { industry: "食品饮料", delta: 0.08 },
        largest_decrease: { industry: "汽车", delta: -0.05 },
        implicit_exposure_sum: 0.94,
      },
      top_industries: [{ industry: "食品饮料", exposure: 0.6 }],
      all_industries: [{ industry: "食品饮料", exposure: 0.6 }],
      four_week_changes: { from_date: "2026-07-10", to_date: "2026-08-07", increases: [], decreases: [] },
      trend: [],
      disclosure_comparison: [],
      credibility: null,
      diagnostics: { converged: true, parameters: {} },
      downloads: [],
    };
    const fetchMock = vi.fn((url) => {
      if (url === "/api/health") {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok", app: "FundTrace", git_commit: "edc4455" }), { status: 200 }));
      }
      if (url === "/api/results/110022") {
        return Promise.resolve(new Response(JSON.stringify(result), { status: 200 }));
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("本次追踪")).toBeInTheDocument();
    expect(screen.getByText("暂无趋势数据")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/results/110022", undefined);
    expect(fetchMock).not.toHaveBeenCalledWith("/api/analyze", expect.anything());
  });
});
