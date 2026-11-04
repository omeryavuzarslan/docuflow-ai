import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { UserRound } from "lucide-react";

import { api } from "../api/client";
import { useOwner } from "../lib/owner";

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const { owner, setOwner } = useOwner();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.GET("/health")).data ?? null,
    refetchInterval: 15_000,
    retry: false,
  });
  const online = health.data?.status === "ok";

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-200/80 bg-white/80 px-8 backdrop-blur">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-2 text-xs text-slate-500" title="API status">
          <span className={clsx("size-2 rounded-full", online ? "bg-emerald-500" : "bg-rose-500")} />
          {online ? "Connected" : "API offline"}
        </span>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white py-1.5 pl-2.5 pr-1 text-sm shadow-card">
          <UserRound className="size-4 text-slate-400" aria-hidden />
          <span className="sr-only">Workspace</span>
          <select
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            className="bg-transparent pr-1 font-medium text-slate-700 outline-none"
          >
            <option value="demo">demo</option>
            <option value="sandbox">sandbox</option>
          </select>
        </label>
      </div>
    </header>
  );
}
