import { Activity, Clock, RefreshCcw, ShieldCheck } from "lucide-react";
import { AnalysisPanel } from "./AnalysisPanel";
import { FundSearch } from "./FundSearch";
import { Navbar } from "./Navbar";

const metadata = [
  [Activity, "周频行业暴露", null],
  [ShieldCheck, "本地分析", null],
  [Clock, "约15秒快速分析", "使用本地已有数据，不含必要的数据联网更新时间"],
];

export function Hero({ uiState, jobStatus, elapsed, message, error, currentFundCode, onAnalyze }) {
  const analyzing = uiState === "analyzing";
  return (
    <section className={`hero-shell relative z-10 flex min-h-screen flex-col ${analyzing ? "is-analyzing" : ""}`}>
      <Navbar />
      <main className="flex flex-1 flex-col justify-end px-4 pb-10 sm:px-6 md:px-12 md:pb-16">
        <div className="hero-content max-w-[1100px]">
          <div className="hero-copy">
            <div className="animate-blur-fade-up mb-6 flex flex-wrap gap-x-6 gap-y-3 text-xs text-zinc-400" style={{ animationDelay: "200ms" }}>
              {metadata.map(([Icon, label, title]) => (
                <span key={label} className="flex items-center gap-2" title={title || undefined}><Icon size={14} /> {label}</span>
              ))}
            </div>
            <p className="animate-blur-fade-up mb-3 text-xs uppercase tracking-[0.26em] text-zinc-500" style={{ animationDelay: "300ms" }}>
              Trace the fund. Read the shift.
            </p>
            <h1 className="animate-blur-fade-up max-w-[980px] text-4xl font-normal leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl md:text-6xl lg:text-7xl" style={{ animationDelay: "300ms" }}>
              看见披露空窗期里的变化
            </h1>
            <div className="animate-blur-fade-up mt-6 max-w-[700px] text-sm leading-7 text-zinc-400 sm:text-base" style={{ animationDelay: "400ms" }}>
              <p>基于公开持仓披露、基金净值和行业收益，估算主动权益基金近期的周频隐含行业暴露与调仓方向。</p>
              <p className="mt-1 text-zinc-500">结果用于趋势观察，不代表基金当前真实完整持仓。</p>
            </div>
          </div>

          <div className="mt-8 max-w-[650px]">
            {analyzing ? (
              <AnalysisPanel fundCode={currentFundCode} status={jobStatus} elapsed={elapsed} message={message} />
            ) : (
              <>
                {error && (
                  <div className="liquid-glass mb-4 rounded-2xl p-4 text-sm text-zinc-300">
                    <p>{error.message}</p>
                    {error.canUseLocalData && (
                      <button
                        type="button"
                        className="mt-3 flex items-center gap-2 text-xs text-white"
                        onClick={() => onAnalyze(error.fundCode, false)}
                      >
                        <RefreshCcw size={14} /> 使用已有本地数据继续分析
                      </button>
                    )}
                  </div>
                )}
                <FundSearch onAnalyze={onAnalyze} initialCode={error?.fundCode || ""} />
              </>
            )}
          </div>
        </div>
      </main>
    </section>
  );
}
