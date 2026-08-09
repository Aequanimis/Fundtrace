import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import App from "./App";

const enabled = process.env.FUNDTRACE_E2E === "1";
const liveSuite = enabled ? describe : describe.skip;
const nativeFetch = globalThis.fetch;

liveSuite("FundTrace live UI flow", () => {
  beforeAll(() => {
    globalThis.fetch = (resource, options) => {
      const url = new URL(resource, "http://127.0.0.1:8765/");
      if (url.pathname === "/api/analyze" && process.env.FUNDTRACE_EXISTING_JOB_ID) {
        return Promise.resolve(new Response(JSON.stringify({
          job_id: process.env.FUNDTRACE_EXISTING_JOB_ID,
        }), { headers: { "Content-Type": "application/json" }, status: 202 }));
      }
      return nativeFetch(url, options);
    };
  });

  afterAll(() => {
    globalThis.fetch = nativeFetch;
  });

  test("analyzes 161005 from the form and renders the dashboard", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("基金代码"), {
      target: { value: "161005" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "更新最新数据" }));
    fireEvent.click(screen.getByRole("button", { name: /开始分析/ }));

    expect(screen.getByText("正在分析 161005")).toBeInTheDocument();
    expect(await screen.findByText("本次追踪", {}, { timeout: 30_000 })).toBeInTheDocument();
    expect(screen.getByText("当前隐含行业暴露")).toBeInTheDocument();
    expect(screen.getByText("过去一年行业暴露变化")).toBeInTheDocument();
  }, 35_000);
});
