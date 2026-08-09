import { lazy, Suspense } from "react";
import { CinematicBackground } from "./components/CinematicBackground";
import { Hero } from "./components/Hero";
import { useAnalysisJob } from "./hooks/useAnalysisJob";

const ResultsDashboard = lazy(() =>
  import("./components/ResultsDashboard").then((module) => ({
    default: module.ResultsDashboard,
  })),
);

export default function App() {
  const analysis = useAnalysisJob();
  const backgroundState = analysis.uiState === "success" ? "results" : analysis.uiState;

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
    </div>
  );
}
