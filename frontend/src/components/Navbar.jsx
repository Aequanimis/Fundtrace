import { Menu, Settings, X } from "lucide-react";
import { useState } from "react";
import { MODEL_VERSION, PRODUCT_NAME } from "../config/branding";

const links = [
  ["分析", "#analysis"],
  ["趋势", "#trends"],
  ["方法", "#method"],
  ["关于", "#about"],
];

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <nav className="relative z-50 flex items-center justify-between px-4 py-4 sm:px-6 md:px-12 md:py-6">
      <a href="#analysis" className="animate-blur-fade-up flex items-baseline gap-3" aria-label="FundTrace 首页">
        <span className="text-lg font-medium tracking-[-0.03em] text-white">{PRODUCT_NAME}</span>
        <span className="hidden text-[11px] text-zinc-500 sm:inline">基金高频持仓追踪</span>
      </a>

      <div className="hidden items-center gap-8 text-sm text-zinc-400 lg:flex">
        {links.map(([label, href]) => (
          <a key={label} href={href} className="transition-colors hover:text-white">
            {label}
          </a>
        ))}
      </div>

      <div className="relative flex items-center gap-2">
        <button
          type="button"
          className="liquid-glass hidden rounded-full px-4 py-2 text-xs text-zinc-300 sm:block"
          onClick={() => setSettingsOpen((value) => !value)}
        >
          {MODEL_VERSION}
        </button>
        <button
          type="button"
          className="liquid-glass grid h-10 w-10 place-items-center rounded-full text-zinc-300"
          aria-label="模型信息"
          onClick={() => setSettingsOpen((value) => !value)}
        >
          <Settings size={16} />
        </button>
        <button
          type="button"
          className="liquid-glass grid h-10 w-10 place-items-center rounded-full text-zinc-300 lg:hidden"
          aria-label={mobileOpen ? "关闭菜单" : "打开菜单"}
          onClick={() => setMobileOpen((value) => !value)}
        >
          {mobileOpen ? <X size={17} /> : <Menu size={17} />}
        </button>

        {settingsOpen && (
          <div className="liquid-glass absolute right-0 top-14 w-64 rounded-2xl p-5 text-sm text-zinc-300">
            <button
              type="button"
              className="absolute right-3 top-3 text-zinc-500 hover:text-white"
              onClick={() => setSettingsOpen(false)}
              aria-label="关闭模型信息"
            >
              <X size={15} />
            </button>
            <p className="mb-4 text-xs uppercase tracking-[0.18em] text-zinc-500">Model status</p>
            <dl className="space-y-3">
              <div><dt className="text-zinc-500">模型版本</dt><dd>v4-a2.1-stable</dd></div>
              <div><dt className="text-zinc-500">当前模式</dt><dd>Stable MVP</dd></div>
              <div><dt className="text-zinc-500">Research</dt><dd>Not Enabled</dd></div>
            </dl>
          </div>
        )}

        {mobileOpen && (
          <div className="liquid-glass absolute right-0 top-14 w-44 rounded-2xl p-3 lg:hidden">
            {links.map(([label, href]) => (
              <a
                key={label}
                href={href}
                className="block rounded-xl px-3 py-2 text-sm text-zinc-300 hover:bg-white/5 hover:text-white"
                onClick={() => setMobileOpen(false)}
              >
                {label}
              </a>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
