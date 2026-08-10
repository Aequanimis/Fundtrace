import { ArrowRight, ChartNoAxesCombined } from "lucide-react";
import { useState } from "react";

export function FundSearch({ onAnalyze, disabled = false, initialCode = "" }) {
  const [fundCode, setFundCode] = useState(initialCode);
  const [updateData, setUpdateData] = useState(true);
  const [validation, setValidation] = useState("");

  const submit = (event) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(fundCode)) {
      setValidation("请输入6位基金代码");
      return;
    }
    setValidation("");
    onAnalyze(fundCode, updateData);
  };

  return (
    <form id="analysis" onSubmit={submit} className="animate-blur-fade-up hero-search" style={{ animationDelay: "500ms" }}>
      <div className="liquid-glass search-shell rounded-[28px] sm:rounded-full">
        <div className="flex min-w-0 flex-1 items-center gap-3 px-5 sm:px-6">
          <ChartNoAxesCombined size={20} className="shrink-0 text-zinc-500" />
          <input
            value={fundCode}
            onChange={(event) => setFundCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoComplete="off"
            placeholder="输入6位基金代码，例如 161005"
            aria-label="基金代码"
            className="h-16 min-w-0 flex-1 bg-transparent text-lg text-white outline-none placeholder:text-zinc-500 sm:h-[72px]"
            disabled={disabled}
          />
        </div>
        <button
          type="submit"
          disabled={disabled}
          className="primary-cta m-1.5 flex h-14 items-center justify-center gap-2 rounded-full bg-white px-8 text-lg font-medium text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50 sm:h-[62px]"
        >
          开始分析 <ArrowRight size={16} />
        </button>
      </div>
      <div className="mt-3 flex flex-col gap-2 px-1 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
        <span>{validation || "使用本地数据通常更快；更新数据耗时取决于网络和数据源响应"}</span>
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={updateData}
            onChange={(event) => setUpdateData(event.target.checked)}
            className="accent-white"
          />
          更新最新数据
        </label>
      </div>
    </form>
  );
}
