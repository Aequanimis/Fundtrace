import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

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
});
