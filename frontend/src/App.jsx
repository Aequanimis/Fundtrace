import { useCallback, useEffect, useState } from "react";
import { CinematicBackground } from "./components/CinematicBackground";
import { Hero } from "./components/Hero";
import { ResultDashboardBoundary } from "./components/ResultDashboardBoundary";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { useAnalysisJob } from "./hooks/useAnalysisJob";
import { getRuntimeIdentity } from "./lib/api";

function RuntimeBuildInfo({ identity }) {
  const commit = identity?.git_commit;
  if (typeof commit !== "string" || commit.length < 7 || commit === "unknown") return null;

  return (
    <p
      aria-label="FundTrace build"
      className="pointer-events-none fixed bottom-3 right-4 z-40 text-[10px] tracking-[0.08em] text-zinc-500/80 sm:bottom-4 sm:right-6"
    >
      FundTrace v1.2 · Build {commit.slice(0, 7)}
    </p>
  );
}

export default function App() {
  const analysis = useAnalysisJob();
  const [runtimeIdentity, setRuntimeIdentity] = useState(null);
  const backgroundState = analysis.uiState === "success" ? "results" : analysis.uiState;

  const resetToHome = useCallback(() => {
    analysis.reset();
    const url = new URL(window.location.href);
    url.searchParams.delete("result");
    window.history.replaceState(null, "", url);
  }, [analysis.reset]);

  useEffect(() => {
    let active = true;
    getRuntimeIdentity()
      .then((identity) => {
        if (active && identity?.app === "FundTrace") setRuntimeIdentity(identity);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const savedFundCode = new URLSearchParams(window.location.search).get("result");
    if (/^\d{6}$/.test(savedFundCode || "")) analysis.loadSavedResult(savedFundCode);
  }, [analysis.loadSavedResult]);

  useEffect(() => {
    const code = analysis.result?.fund_code;
    if (analysis.uiState !== "success" || !/^\d{6}$/.test(code || "")) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("result") === code) return;
    url.searchParams.set("result", code);
    window.history.replaceState(null, "", url);
  }, [analysis.result, analysis.uiState]);

  return (
    <div className={`app-shell ${analysis.uiState}`}>
      <CinematicBackground state={backgroundState} />
      {analysis.uiState === "success" && analysis.result ? (
        <ResultDashboardBoundary onReset={resetToHome}>
          <ResultsDashboard
            data={analysis.result}
            onReset={resetToHome}
            onAnalyze={analysis.startAnalysis}
          />
        </ResultDashboardBoundary>
      ) : (
        <Hero
          currentFundCode={analysis.fundCode}
          uiState={analysis.uiState}
          jobStatus={analysis.jobStatus}
          elapsed={analysis.elapsed}
          message={analysis.message}
          error={analysis.error}
          onAnalyze={analysis.startAnalysis}
        />
      )}
      <RuntimeBuildInfo identity={runtimeIdentity} />
    </div>
  );
}
