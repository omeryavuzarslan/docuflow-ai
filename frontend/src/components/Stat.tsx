import clsx from "clsx";
import type { ReactNode } from "react";

export function Stat({ label, value, icon, tone }: { label: string; value: number | string; icon: ReactNode; tone: string }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card">
      <span className={clsx("grid size-10 place-items-center rounded-xl", tone)}>{icon}</span>
      <div>
        <div className="text-2xl font-semibold tracking-tight tabular">{value}</div>
        <div className="text-xs font-medium text-slate-500">{label}</div>
      </div>
    </div>
  );
}
