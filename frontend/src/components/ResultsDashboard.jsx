import {
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  Download,
  RefreshCcw,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const TREND_COLORS = ["#4DA3FF", "#FFB547", "#2DD4BF", "#E879F9", "#A3E635", "#FB7185", "#A78BFA", "#38BDF8"];
export const FONT_SCALES = [90, 100, 115, 130];
const FONT_SCALE_KEY = "fundtrace-font-scale";
const EMPTY_LABEL = "—";
const asArray = (value) => Array.isArray(value) ? value : [];
const asRecord = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const asText = (value, fallback = EMPTY_LABEL) => typeof value === "string" && value.trim() ? value : fallback;
const finiteNumber = (value, fallback = 0) => {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const percentage = (value, digits = 1) => `${(finiteNumber(value) * 100).toFixed(digits)}%`;
const points = (value) => {
  const number = finiteNumber(value);
  return `${number >= 0 ? "+" : ""}${(number * 100).toFixed(1)}pp`;
};

function normalizeIndustryItem(value) {
  const item = asRecord(value);
  const industry = asText(item.industry, "");
  return industry ? { industry, exposure: finiteNumber(item.exposure) } : null;
}

function normalizeChangeItem(value) {
  const item = asRecord(value);
  const industry = asText(item.industry, "");
  return industry ? { industry, delta: finiteNumber(item.delta) } : null;
}

function normalizeIndustryItems(values) {
  return asArray(values).map(normalizeIndustryItem).filter(Boolean);
}

function normalizeChangeItems(values) {
  return asArray(values).map(normalizeChangeItem).filter(Boolean);
}

export function normalizeDashboardData(value) {
  const data = asRecord(value);
  const allIndustries = normalizeIndustryItems(data.all_industries);
  const sourceTopIndustries = normalizeIndustryItems(data.top_industries);
  const topIndustries = sourceTopIndustries.length ? sourceTopIndustries : allIndustries.slice(0, 10);
  const summary = asRecord(data.summary);
  const fourWeekChanges = asRecord(data.four_week_changes);
  const diagnostics = asRecord(data.diagnostics);
  const parameters = asRecord(diagnostics.parameters);
  const credibility = asRecord(data.credibility);
  const credibilityGrade = asText(credibility.grade, "");
  const credibilityLabel = asText(credibility.label, "");

  return {
    fund_code: asText(data.fund_code),
    latest_date: asText(data.latest_date),
    analysis_time: finiteNumber(data.analysis_time, null),
    summary: {
      sentence: asText(summary.sentence, "暂无结果摘要。"),
      main_industry: normalizeIndustryItem(summary.main_industry) || { industry: EMPTY_LABEL, exposure: 0 },
      largest_increase: normalizeChangeItem(summary.largest_increase) || { industry: EMPTY_LABEL, delta: 0 },
      largest_decrease: normalizeChangeItem(summary.largest_decrease) || { industry: EMPTY_LABEL, delta: 0 },
      implicit_exposure_sum: finiteNumber(summary.implicit_exposure_sum),
    },
    top_industries: topIndustries,
    all_industries: allIndustries.length ? allIndustries : topIndustries,
    four_week_changes: {
      from_date: asText(fourWeekChanges.from_date),
      to_date: asText(fourWeekChanges.to_date),
      increases: normalizeChangeItems(fourWeekChanges.increases),
      decreases: normalizeChangeItems(fourWeekChanges.decreases),
    },
    trend: asArray(data.trend).map((row) => {
      const item = asRecord(row);
      const date = asText(item.date, "");
      if (!date) return null;
      const values = Object.fromEntries(
        Object.entries(asRecord(item.values)).map(([industry, exposure]) => [
          String(industry),
          finiteNumber(exposure, null),
        ]),
      );
      return { date: date.slice(5), values };
    }).filter(Boolean),
    disclosure_comparison: asArray(data.disclosure_comparison).map((row) => {
      const item = asRecord(row);
      const industry = asText(item.industry, "");
      return industry ? {
        industry,
        disclosed: finiteNumber(item.disclosed),
        current: finiteNumber(item.current),
        delta: finiteNumber(item.delta),
      } : null;
    }).filter(Boolean),
    credibility: credibilityGrade && credibilityLabel ? { grade: credibilityGrade, label: credibilityLabel } : null,
    diagnostics: {
      r2: finiteNumber(diagnostics.r2, null),
      converged: diagnostics.converged === true || String(diagnostics.converged).toLowerCase() === "true",
      model_version: asText(diagnostics.model_version),
      parameters: {
        window: finiteNumber(parameters.window, null),
        half_life: finiteNumber(parameters.half_life, null),
        alpha: finiteNumber(parameters.alpha, null),
      },
      data_cutoff: asText(diagnostics.data_cutoff),
    },
    downloads: asArray(data.downloads).map((item) => {
      const download = asRecord(item);
      const filename = asText(download.filename, "");
      const url = asText(download.url, "");
      return filename && url ? { filename, url, label: asText(download.label, filename) } : null;
    }).filter(Boolean),
  };
}

export function readFontScale(storage) {
  try {
    const stored = Number(storage?.getItem?.(FONT_SCALE_KEY));
    return FONT_SCALES.includes(stored) ? stored : 115;
  } catch {
    return 115;
  }
}

export function persistFontScale(storage, value) {
  try {
    storage?.setItem?.(FONT_SCALE_KEY, String(FONT_SCALES.includes(value) ? value : 115));
  } catch {
    // Storage can be unavailable in restrictive browser modes; rendering must continue.
  }
}

export function resolveSelectedColors(selected, industryColors) {
  const used = new Set();
  const colors = asRecord(industryColors);
  return Object.fromEntries(asArray(selected).filter((industry) => typeof industry === "string" && industry).map((industry) => {
    const preferred = Math.max(0, TREND_COLORS.indexOf(colors[industry]));
    let color = TREND_COLORS[preferred];
    for (let offset = 0; offset < TREND_COLORS.length; offset += 1) {
      const candidate = TREND_COLORS[(preferred + offset) % TREND_COLORS.length];
      if (!used.has(candidate)) {
        color = candidate;
        break;
      }
    }
    used.add(color);
    return [industry, color];
  }));
}

function MetricCard({ eyebrow, value, detail }) {
  return (
    <article className="result-card min-h-40 p-5 sm:p-6">
      <p className="text-xs text-zinc-500">{eyebrow}</p>
      <p className="mt-8 text-2xl tracking-[-0.035em] text-white sm:text-3xl">{value}</p>
      <p className="mt-2 text-sm text-zinc-500">{detail}</p>
    </article>
  );
}

function ChangeList({ title, items, direction }) {
  const Icon = direction === "up" ? ArrowUpRight : ArrowDownRight;
  const tone = direction === "up" ? "text-emerald-300/80" : "text-rose-300/80";
  return (
    <article className="result-card p-5 sm:p-6">
      <h3 className="flex items-center gap-2 text-sm text-zinc-300"><Icon size={16} className={tone} /> {title}</h3>
      <div className="mt-5 divide-y divide-white/[0.06]">
        {items.length ? items.map((item) => (
          <div key={item.industry} className="flex items-center justify-between py-3 text-sm">
            <span className="text-zinc-300">{item.industry}</span>
            <span className={tone}>{points(item.delta)}</span>
          </div>
        )) : <p className="py-4 text-sm text-zinc-600">最近四周没有明显变化</p>}
      </div>
    </article>
  );
}

function FontScaleControl({ value, onChange }) {
  const index = FONT_SCALES.indexOf(value);
  return (
    <div className="font-scale-control" role="group" aria-label="Dashboard font size">
      <button type="button" aria-label="Decrease font size" disabled={index <= 0} onClick={() => onChange(FONT_SCALES[index - 1])}>A−</button>
      <output aria-label="Current font size">{value}%</output>
      <button type="button" aria-label="Increase font size" disabled={index >= FONT_SCALES.length - 1} onClick={() => onChange(FONT_SCALES[index + 1])}>A+</button>
    </div>
  );
}

function TrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-black/90 px-4 py-3 text-sm shadow-2xl backdrop-blur-xl">
      <p className="mb-2 text-zinc-500">{label}</p>
      <div className="space-y-1.5">
        {payload.filter(Boolean).map((entry) => {
          const color = typeof entry.color === "string" && entry.color ? entry.color : TREND_COLORS[0];
          return (
          <p key={String(entry.dataKey)} className="flex items-center justify-between gap-6 text-zinc-300">
            <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{String(entry.dataKey || EMPTY_LABEL)}</span>
            <span style={{ color }}>{percentage(entry.value)}</span>
          </p>
          );
        })}
      </div>
    </div>
  );
}

export function ModelStatus({ credibility, diagnostics, analysisTime }) {
  const safeDiagnostics = asRecord(diagnostics);
  const parameters = asRecord(safeDiagnostics.parameters);
  const isConverged = safeDiagnostics.converged === true || String(safeDiagnostics.converged).toLowerCase() === "true";
  const ConvergenceIcon = isConverged ? CheckCircle2 : TriangleAlert;
  const convergenceTone = isConverged ? "text-emerald-300/80" : "text-amber-300/80";
  return (
    <div className="result-card mt-8 p-6">
      {credibility && (
        <div
          className="mb-6 inline-flex rounded-full bg-white/[0.06] px-3 py-1.5 text-sm text-zinc-200"
          aria-label={`可信度 ${credibility.grade} ${credibility.label}`}
        >
          {credibility.grade} · {credibility.label}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <CheckCircle2 size={15} className="text-emerald-300/80" /> 分析完成
        </p>
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <ConvergenceIcon
            size={15}
            className={convergenceTone}
            data-testid={isConverged ? "convergence-ok-icon" : "convergence-warning-icon"}
          />
          {isConverged ? "最新窗口正常收敛" : "最新窗口需关注"}
        </p>
        <p className="flex items-center gap-2 text-sm text-zinc-300">
          <CheckCircle2 size={15} className="text-emerald-300/80" /> 数据可用
        </p>
      </div>
      <details className="mt-7 border-t border-white/[0.07] pt-5 text-sm text-zinc-400">
        <summary className="cursor-pointer select-none text-zinc-300">高级信息</summary>
        <dl className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <div><dt>最新 R²</dt><dd>{Number.isFinite(safeDiagnostics.r2) ? safeDiagnostics.r2.toFixed(3) : "—"}</dd></div>
          <div><dt>Converged</dt><dd>{String(isConverged)}</dd></div>
          <div><dt>模型版本</dt><dd>{asText(safeDiagnostics.model_version)}</dd></div>
          <div><dt>模型运行时间</dt><dd>{Number.isFinite(analysisTime) ? `${analysisTime.toFixed(2)}s` : "—"}</dd></div>
          <div><dt>窗口</dt><dd>{parameters.window ?? "—"}</dd></div>
          <div><dt>半衰期</dt><dd>{parameters.half_life ?? "—"}</dd></div>
          <div><dt>Alpha</dt><dd>{parameters.alpha ?? "—"}</dd></div>
          <div><dt>数据截止日</dt><dd>{asText(safeDiagnostics.data_cutoff)}</dd></div>
        </dl>
      </details>
    </div>
  );
}

export function ResultsDashboard({ data, onReset, onAnalyze }) {
  const dashboard = useMemo(() => normalizeDashboardData(data), [data]);
  const [showAll, setShowAll] = useState(false);
  const defaults = dashboard.top_industries.slice(0, 5).map((item) => item.industry);
  const [selected, setSelected] = useState(defaults);
  const [fontScale, setFontScale] = useState(() => {
    try {
      return readFontScale(window.localStorage);
    } catch {
      return 115;
    }
  });
  const chartIndustries = showAll ? dashboard.all_industries : dashboard.top_industries;
  const industryColors = useMemo(
    () => Object.fromEntries(dashboard.all_industries.map((item, index) => [item.industry, TREND_COLORS[index % TREND_COLORS.length]])),
    [dashboard.all_industries],
  );
  const selectedColors = useMemo(
    () => resolveSelectedColors(selected, industryColors),
    [industryColors, selected],
  );
  const chartFontSize = Math.round(11 * fontScale / 100);
  const trendData = useMemo(
    () => dashboard.trend.map((row) => ({ date: row.date, ...row.values })),
    [dashboard.trend],
  );

  const toggleIndustry = (industry) => {
    setSelected((current) => {
      if (current.includes(industry)) return current.filter((item) => item !== industry);
      return current.length < 8 ? [...current, industry] : current;
    });
  };

  useEffect(() => {
    try {
      persistFontScale(window.localStorage, fontScale);
    } catch {
      // Rendering must not depend on localStorage availability.
    }
  }, [fontScale]);

  const scrollToDownloads = () => document.getElementById("downloads")?.scrollIntoView({ behavior: "smooth" });

  return (
    <main className="results-dashboard results-enter relative z-20 min-h-screen bg-black text-white" style={{ "--dashboard-scale": fontScale / 100 }}>
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-black/90 px-4 py-4 backdrop-blur-xl sm:px-6 md:px-12">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-5">
            <button type="button" onClick={onReset} className="text-base font-medium tracking-[-0.03em]">FundTrace</button>
            <div className="hidden h-4 w-px bg-white/10 sm:block" />
            <p className="truncate text-xs text-zinc-500">基金代码 <span className="ml-2 text-zinc-300">{dashboard.fund_code}</span></p>
            <p className="hidden text-xs text-zinc-500 md:block">最新分析 <span className="ml-2 text-zinc-300">{dashboard.latest_date}</span></p>
          </div>
          <div className="flex items-center gap-2">
            <FontScaleControl value={fontScale} onChange={setFontScale} />
            <button type="button" onClick={() => onAnalyze(dashboard.fund_code, false)} className="secondary-button"><RefreshCcw size={14} /> 重新分析</button>
            <button type="button" onClick={scrollToDownloads} className="primary-small"><Download size={14} /> 下载</button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1440px] px-4 pb-24 pt-16 sm:px-6 md:px-12 md:pt-24">
        <section id="analysis" className="scroll-mt-24">
          <p className="section-index">01 / 本次追踪</p>
          <h1 className="mt-4 text-3xl font-normal tracking-[-0.04em] sm:text-4xl md:text-5xl">本次追踪</h1>
          <p className="mt-5 max-w-3xl text-base leading-7 text-zinc-400">{dashboard.summary.sentence}</p>
          <div className="mt-10 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard eyebrow="主要行业" value={dashboard.summary.main_industry.industry} detail={percentage(dashboard.summary.main_industry.exposure)} />
            <MetricCard eyebrow="近期增加" value={dashboard.summary.largest_increase.industry} detail={points(dashboard.summary.largest_increase.delta)} />
            <MetricCard eyebrow="近期减少" value={dashboard.summary.largest_decrease.industry} detail={points(dashboard.summary.largest_decrease.delta)} />
            <MetricCard eyebrow="隐含权益暴露" value={percentage(dashboard.summary.implicit_exposure_sum)} detail="收益口径估算" />
          </div>
        </section>

        <section className="result-section">
          <div className="mb-8 flex items-end justify-between gap-4">
            <div><p className="section-index">02 / 当前行业暴露</p><h2 className="section-title">当前隐含行业暴露</h2><p className="section-subtitle">最新周频估算 · {dashboard.latest_date}</p></div>
            <button type="button" className="secondary-button hidden sm:flex" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "收起" : "查看全部行业"} <ChevronDown size={14} className={showAll ? "rotate-180" : ""} />
            </button>
          </div>
          <div className="result-card h-[460px] px-2 py-5 sm:px-6">
            {chartIndustries.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartIndustries} layout="vertical" margin={{ top: 10, right: 28, left: 18, bottom: 4 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" tickFormatter={(value) => percentage(value, 0)} stroke="#52525b" tick={{ fontSize: chartFontSize }} />
                  <YAxis type="category" dataKey="industry" width={Math.round(76 * fontScale / 100)} stroke="#71717a" tick={{ fontSize: chartFontSize }} />
                  <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} contentStyle={{ background: "#090909", border: "1px solid rgba(255,255,255,.1)", borderRadius: 12 }} formatter={(value) => [percentage(value), "隐含暴露"]} />
                  <Bar dataKey="exposure" fill="#f4f4f5" radius={[0, 5, 5, 0]} maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="grid h-full place-items-center text-sm text-zinc-600">暂无当前行业暴露数据</p>}
          </div>
          <button type="button" className="secondary-button mt-4 w-full justify-center sm:hidden" onClick={() => setShowAll((value) => !value)}>{showAll ? "收起" : "查看全部行业"}</button>
        </section>

        <section className="result-section">
          <p className="section-index">03 / 最近4周发生了什么</p>
          <h2 className="section-title">最近4周发生了什么</h2>
          <p className="section-subtitle">{dashboard.four_week_changes.from_date} → {dashboard.four_week_changes.to_date}，单位为百分点（pp）</p>
          <div className="mt-8 grid gap-3 lg:grid-cols-2">
            <ChangeList title="近期增加" items={dashboard.four_week_changes.increases} direction="up" />
            <ChangeList title="近期减少" items={dashboard.four_week_changes.decreases} direction="down" />
          </div>
        </section>

        <section id="trends" className="result-section scroll-mt-24">
          <p className="section-index">04 / 历史趋势</p>
          <h2 className="section-title">过去一年行业暴露变化</h2>
          <p className="section-subtitle">默认显示最新 Top5；最多同时选择 8 个行业</p>
          <div className="mt-7 flex flex-wrap gap-2">
            {dashboard.all_industries.map((item) => (
              <button
                key={item.industry}
                type="button"
                onClick={() => toggleIndustry(item.industry)}
                className={`industry-chip ${selected.includes(item.industry) ? "is-selected" : ""}`}
                style={{ "--chip-color": selectedColors[item.industry] || industryColors[item.industry] }}
              >
                {selected.includes(item.industry) && <span className="industry-chip-dot" aria-hidden="true" />}
                {item.industry}
              </button>
            ))}
          </div>
          <div className="result-card mt-5 h-[440px] p-3 sm:p-6">
            {trendData.length && selected.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ top: 12, right: 12, left: -12, bottom: 4 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="date" stroke="#52525b" tick={{ fontSize: chartFontSize }} minTickGap={32} />
                  <YAxis stroke="#52525b" tick={{ fontSize: chartFontSize }} tickFormatter={(value) => percentage(value, 0)} />
                  <Tooltip content={<TrendTooltip />} />
                  {selected.map((industry) => (
                    <Line key={industry} type="monotone" dataKey={industry} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} stroke={selectedColors[industry] || TREND_COLORS[0]} strokeWidth={2.3} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="grid h-full place-items-center text-sm text-zinc-600">暂无趋势数据</p>}
          </div>
        </section>

        {dashboard.disclosure_comparison.length > 0 && (
          <section className="result-section">
            <p className="section-index">05 / 披露基座 vs 当前模型</p>
            <h2 className="section-title">最近披露基座 vs 当前模型</h2>
            <div className="mt-8 overflow-x-auto result-card">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="border-b border-white/[0.08] text-xs text-zinc-500"><tr><th>行业</th><th>最近披露</th><th>当前估算</th><th>变化</th></tr></thead>
                <tbody>{dashboard.disclosure_comparison.map((row) => <tr key={row.industry} className="border-b border-white/[0.05] last:border-0"><td>{row.industry}</td><td>{percentage(row.disclosed)}</td><td>{percentage(row.current)}</td><td>{points(row.delta)}</td></tr>)}</tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-zinc-600">基于当前 MVP 披露口径，仅供趋势参考。</p>
          </section>
        )}

        <section id="method" className="result-section scroll-mt-24">
          <p className="section-index">06 / 模型状态</p>
          <h2 className="section-title">模型状态</h2>
          <ModelStatus
            credibility={dashboard.credibility}
            diagnostics={dashboard.diagnostics}
            analysisTime={dashboard.analysis_time}
          />
        </section>

        <section id="about" className="result-section scroll-mt-24">
          <p className="section-index">07 / 结果说明</p>
          <h2 className="section-title">如何理解本报告</h2>
          <div className="mt-7 grid gap-6 text-sm leading-7 text-zinc-400 md:grid-cols-2">
            <p>FundTrace 根据公开披露、基金净值和行业收益，估算基金的周频隐含行业暴露。适合观察可能的调仓方向与风格变化。</p>
            <p>结果不等同于基金当前真实完整持仓。个股特异性收益、未完整覆盖资产和披露差异都可能影响估算。</p>
          </div>
        </section>

        <section id="downloads" className="result-section scroll-mt-24 border-b-0">
          <p className="section-index">Downloads</p>
          <h2 className="section-title">下载结果</h2>
          <div className="mt-7 flex flex-wrap gap-3">
            {dashboard.downloads.map((item) => (
              <a key={item.filename} href={item.url} className="secondary-button"><Download size={14} /> {item.label}</a>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
