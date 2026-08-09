async function request(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail[0]?.msg
      : payload.detail;
    throw new Error(detail || "请求未能完成");
  }
  return payload;
}

export function createAnalysis(fundCode, updateData) {
  return request("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fund_code: fundCode, update_data: updateData }),
  });
}

export function getJob(jobId) {
  return request(`/api/jobs/${jobId}`);
}

export function getResults(fundCode) {
  return request(`/api/results/${fundCode}`);
}
