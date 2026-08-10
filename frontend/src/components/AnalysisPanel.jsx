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
    <div className="liquid-glass analysis-panel animate-blur-fade-up rounded-3xl p-7 sm:p-9">
      <div className="mb-9 flex items-start justify-between gap-5">
        <div>
          <p className="mb-3 text-sm uppercase tracking-[0.22em] text-zinc-500">{complete ? "Complete" : "In progress"}</p>
          <h2 className="text-2xl font-normal text-white sm:text-3xl">
            {complete ? "分析完成" : `正在分析 ${fundCode}`}
          </h2>
          <p className="mt-3 text-base text-zinc-500">{message}</p>
        </div>
        <span className="font-mono text-base text-zinc-400">{formatElapsed(elapsed)}</span>
      </div>
      <div className="space-y-5">
        {stages.map(([key, label], index) => {
          const done = rank > index;
          const active = rank === index && !complete;
          return (
            <div key={key} className={`flex items-center gap-4 text-base ${done || active ? "text-zinc-200" : "text-zinc-600"}`}>
              {done ? <Check size={18} /> : active ? <LoaderCircle size={18} className="animate-spin" /> : <Circle size={16} />}
              <span>{label}</span>
            </div>
          );
        })}
      </div>
      {!complete && <div className="indeterminate-track mt-9"><span /></div>}
    </div>
  );
}
