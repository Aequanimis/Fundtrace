import { useCallback, useEffect, useRef, useState } from "react";
import { createAnalysis, getJob, getResults } from "../lib/api";

const sleep = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export function useAnalysisJob() {
  const [fundCode, setFundCode] = useState("161005");
  const [uiState, setUiState] = useState("idle");
  const [jobStatus, setJobStatus] = useState("queued");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const activeRun = useRef(0);

  useEffect(() => {
    if (uiState !== "analyzing") return undefined;
    const started = Date.now() - elapsed * 1000;
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [uiState]);

  const startAnalysis = useCallback(async (fundCode, updateData = true) => {
    setFundCode(fundCode);
    const runId = activeRun.current + 1;
    activeRun.current = runId;
    setUiState("analyzing");
    setJobStatus("queued");
    setElapsed(0);
    setMessage("任务已加入队列");
    setResult(null);
    setError(null);
    try {
      const { job_id: jobId } = await createAnalysis(fundCode, updateData);
      while (activeRun.current === runId) {
        const job = await getJob(jobId);
        setJobStatus(job.status);
        setElapsed(Math.floor(job.elapsed_seconds || 0));
        setMessage(job.message || "正在分析");
        if (job.status === "complete") {
          const data = await getResults(fundCode);
          await sleep(420);
          if (activeRun.current === runId) {
            setResult(data);
            setUiState("success");
          }
          return;
        }
        if (job.status === "error") {
          throw Object.assign(new Error(job.message || "分析未能完成"), {
            canUseLocalData: Boolean(job.can_use_local_data),
            fundCode,
          });
        }
        await sleep(750);
      }
    } catch (reason) {
      if (activeRun.current !== runId) return;
      setError({
        message: reason.message || "分析未能完成",
        canUseLocalData: Boolean(reason.canUseLocalData),
        fundCode,
      });
      setUiState("error");
    }
  }, []);

  const reset = useCallback(() => {
    activeRun.current += 1;
    setUiState("idle");
    setResult(null);
    setError(null);
    setElapsed(0);
  }, []);

  return {
    fundCode,
    uiState,
    jobStatus,
    elapsed,
    message,
    result,
    error,
    startAnalysis,
    reset,
  };
}
