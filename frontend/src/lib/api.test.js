import { afterEach, describe, expect, it, vi } from "vitest";
import { createAnalysis, getJob, getResults } from "./api";


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("FundTrace API client", () => {
  it("uses same-origin relative URLs and the FastAPI payload schema", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: "job-1" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "complete" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ fund_code: "161005" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createAnalysis("161005", false)).resolves.toEqual({ job_id: "job-1" });
    await expect(getJob("job-1")).resolves.toEqual({ status: "complete" });
    await expect(getResults("161005")).resolves.toEqual({ fund_code: "161005" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fund_code: "161005", update_data: false }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/jobs/job-1", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/results/161005", undefined);
  });

  it("converts native fetch failures into a useful network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(createAnalysis("161005", false)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      message: "无法连接本地分析服务，请确认FundTrace仍在运行。",
    });
  });

  it("reports HTTP status and backend detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "请输入6位基金代码",
    }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    })));

    await expect(createAnalysis("161", false)).rejects.toMatchObject({
      code: "HTTP_ERROR",
      status: 422,
      message: "分析请求失败（HTTP 422）：请输入6位基金代码",
    });
  });
});
