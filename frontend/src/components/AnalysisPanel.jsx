import { Check, Circle, LoaderCircle } from "lucide-react";

const stages = [
  ["queued", "准备基金数据"],
  ["fetching", "整理公开持仓信息"],
  ["analyzing", "计算周频行业暴露"],
  ["rendering", "生成分析报告"],
];
const statusRank = { queued: 0, fetching: 1, analyzing: 2, rendering: 3, complete: 4 };

function formatElapsed(seconds) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function AnalysisPanel({ fundCode, status, elapsed, message }) {
  const rank = statusRank[status] ?? 0;
  const complete = status === "complete";
  return (
    <div className="liquid-glass analysis-panel animate-blur-fade-up rounded-3xl p-6 sm:p-8">
      <div className="mb-7 flex items-start justify-between gap-5">
        <div>
          <p className="mb-2 text-xs uppercase tracking-[0.22em] text-zinc-500">{complete ? "Complete" : "In progress"}</p>
          <h2 className="text-xl font-normal text-white sm:text-2xl">
            {complete ? "分析完成" : `正在分析 ${fundCode}`}
          </h2>
          <p className="mt-2 text-sm text-zinc-500">{message}</p>
        </div>
        <span className="font-mono text-sm text-zinc-400">{formatElapsed(elapsed)}</span>
      </div>
      <div className="space-y-4">
        {stages.map(([key, label], index) => {
          const done = rank > index;
          const active = rank === index && !complete;
          return (
            <div key={key} className={`flex items-center gap-3 text-sm ${done || active ? "text-zinc-200" : "text-zinc-600"}`}>
              {done ? <Check size={16} /> : active ? <LoaderCircle size={16} className="animate-spin" /> : <Circle size={14} />}
              <span>{label}</span>
            </div>
          );
        })}
      </div>
      {!complete && <div className="indeterminate-track mt-7"><span /></div>}
    </div>
  );
}
