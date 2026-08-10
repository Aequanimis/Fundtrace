export const API_BASE = "";

export class ApiError extends Error {
  constructor(code, message, { status = null, cause = undefined } = {}) {
    super(message, { cause });
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request(path, options, action = "请求") {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch (cause) {
    throw new ApiError(
      "NETWORK_ERROR",
      "无法连接本地分析服务，请确认FundTrace仍在运行。",
      { cause },
    );
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail[0]?.msg
      : payload.detail;
    const suffix = detail ? `：${detail}` : "";
    throw new ApiError(
      "HTTP_ERROR",
      `${action}失败（HTTP ${response.status}）${suffix}`,
      { status: response.status },
    );
  }
  return payload;
}

export function createAnalysis(fundCode, updateData) {
  return request("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fund_code: fundCode, update_data: updateData }),
  }, "分析请求");
}

export function getJob(jobId) {
  return request(`/api/jobs/${jobId}`, undefined, "任务状态请求");
}

export function getResults(fundCode) {
  return request(`/api/results/${fundCode}`, undefined, "结果读取");
}
