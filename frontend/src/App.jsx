import { lazy, Suspense, useEffect, useState } from "react";
import { CinematicBackground } from "./components/CinematicBackground";
import { Hero } from "./components/Hero";
import { useAnalysisJob } from "./hooks/useAnalysisJob";
import { getRuntimeIdentity } from "./lib/api";

const ResultsDashboard = lazy(() =>
  import("./components/ResultsDashboard").then((module) => ({
    default: module.ResultsDashboard,
  })),
);

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

  return (
    <div className={`app-shell ${analysis.uiState}`}>
      <CinematicBackground state={backgroundState} />
      {analysis.uiState === "success" && analysis.result ? (
        <Suspense fallback={<div className="min-h-screen bg-black" />}>
          <ResultsDashboard
            data={analysis.result}
            onReset={analysis.reset}
            onAnalyze={analysis.startAnalysis}
          />
        </Suspense>
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
