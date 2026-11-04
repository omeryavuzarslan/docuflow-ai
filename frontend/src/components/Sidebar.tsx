import clsx from "clsx";
import { AlertOctagon, FileStack, MessageSquareText } from "lucide-react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/documents", label: "Documents", icon: FileStack },
  { to: "/findings", label: "Findings", icon: AlertOctagon },
  { to: "/ask", label: "Ask", icon: MessageSquareText },
];

export function Sidebar({ openFindings }: { openFindings?: number }) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200/80 bg-white">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <img src="/favicon.svg" alt="" className="size-8" />
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">DocuFlow AI</div>
          <div className="text-xs text-slate-500">Accounts payable</div>
        </div>
      </div>
      <nav className="flex flex-col gap-0.5 px-3 py-2">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )
            }
          >
            <Icon className="size-[18px]" aria-hidden />
            <span className="flex-1">{label}</span>
            {label === "Findings" && !!openFindings && (
              <span className="rounded-full bg-rose-500 px-2 py-0.5 text-[11px] font-semibold text-white tabular">
                {openFindings}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto p-4 text-xs leading-relaxed text-slate-400">
        Numbers come from your documents and deterministic checks; AI only reads and cites.
      </div>
    </aside>
  );
}
