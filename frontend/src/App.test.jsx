import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("FundTrace UI", () => {
  it("renders the cinematic hero and fund-code entry", () => {
    render(<App />);
    expect(screen.getByText("看见披露空窗期里的变化")).toBeInTheDocument();
    expect(screen.getByLabelText("基金代码")).toHaveAttribute("placeholder", "输入6位基金代码，例如 161005");
    expect(screen.getByRole("button", { name: /开始分析/ })).toBeInTheDocument();
  });
});
