import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FundTrace UI", () => {
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
    render(<App />);

    fireEvent.change(screen.getByLabelText("基金代码"), { target: { value: "161005" } });
    fireEvent.click(screen.getByRole("button", { name: /开始分析/ }));

    expect(await screen.findByText("分析请求失败（HTTP 422）：测试请求无效"))
      .toBeInTheDocument();
  });
});
