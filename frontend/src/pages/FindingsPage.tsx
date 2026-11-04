import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Calculator,
  Check,
  ChevronRight,
  Copy,
  Link2Off,
  Loader2,
  PoundSterling,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api, type Discrepancy, type DocumentSummary } from "../api/client";
import { Stat } from "../components/Stat";
import { TopBar } from "../components/TopBar";
import { countByStatus, inGroup, moneyAtRisk, RULES, TYPE_GROUPS, type GroupKey } from "../lib/findings";
import { docTypeLabel, formatMoney, humanise } from "../lib/format";

const STATUSES = [
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "dismissed", label: "Dismissed" },
  { key: "all", label: "All" },
] as const;
type StatusKey = (typeof STATUSES)[number]["key"];

const GROUP_ICON: Record<string, { icon: typeof Calculator; tone: string }> = {
  matching: { icon: Link2Off, tone: "bg-amber-50 text-amber-600" },
  arithmetic: { icon: Calculator, tone: "bg-rose-50 text-rose-600" },
  duplicate: { icon: Copy, tone: "bg-violet-50 text-violet-600" },
};

function groupOf(type: string) {
  return TYPE_GROUPS.find((g) => (g.types as readonly string[]).includes(type))?.key ?? "matching";
}

export function FindingsPage() {
  const findings = useQuery({
    queryKey: ["discrepancies", "all"],
    queryFn: async () => (await api.GET("/discrepancies")).data ?? [],
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: async () => (await api.GET("/documents", { params: { query: { limit: 500 } } })).data ?? [],
  });
  const [status, setStatus] = useState<StatusKey>("open");
  const [group, setGroup] = useState<GroupKey>("all");

  const all = useMemo(() => findings.data ?? [], [findings.data]);
  const docs = useMemo(() => new Map((documents.data ?? []).map((d) => [d.id, d])), [documents.data]);
  const counts = countByStatus(all);
  const open = all.filter((f) => f.status === "open");
  const byStatus = all.filter((f) => status === "all" || f.status === status);
  const shown = byStatus.filter((f) => inGroup(f, group));

  return (
    <>
      <TopBar title="Findings" subtitle="Discrepancies found by deterministic checks across invoices, POs and delivery notes" />
      <div className="mx-auto max-w-6xl space-y-6 p-8 animate-fade-in">
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Open findings" value={counts.open} icon={<ShieldAlert className="size-5" />} tone="bg-rose-50 text-rose-600" />
          <Stat
            label="Money at risk (open)"
            value={formatMoney(moneyAtRisk(open))}
            icon={<PoundSterling className="size-5" />}
            tone="bg-amber-50 text-amber-600"
          />
          <Stat
            label="Resolved or dismissed"
            value={counts.resolved + counts.dismissed}
            icon={<ShieldCheck className="size-5" />}
            tone="bg-emerald-50 text-emerald-600"
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-xl bg-slate-200/60 p-1">
            {STATUSES.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => setStatus(s.key)}
                className={clsx(
                  "rounded-lg px-3.5 py-1.5 text-sm font-medium transition",
                  status === s.key ? "bg-white text-slate-900 shadow-card" : "text-slate-600 hover:text-slate-900",
                )}
              >
                {s.label}
                {s.key !== "all" && <span className="ml-1.5 text-xs text-slate-400 tabular">{counts[s.key]}</span>}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {[{ key: "all" as const, label: "All types" }, ...TYPE_GROUPS].map((g) => {
              const n = byStatus.filter((f) => inGroup(f, g.key)).length;
              return (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => setGroup(g.key)}
                  className={clsx(
                    "rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition",
                    group === g.key
                      ? "bg-brand-600 text-white ring-brand-600"
                      : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50",
                  )}
                >
                  {g.label} <span className="tabular opacity-70">{n}</span>
                </button>
              );
            })}
          </div>
        </div>

        {findings.isLoading ? (
          <div className="grid h-48 place-items-center">
            <Loader2 className="size-5 animate-spin text-slate-400" />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState status={status} />
        ) : (
          <ul className="space-y-3">
            {shown.map((f) => (
              <FindingRow key={f.id} finding={f} doc={docs.get(f.document_id)} related={f.related_document_id ? docs.get(f.related_document_id) : undefined} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function FindingRow({ finding: f, doc, related }: { finding: Discrepancy; doc?: DocumentSummary; related?: DocumentSummary }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: async (next: "open" | "resolved" | "dismissed") => {
      const { data, error } = await api.PATCH("/discrepancies/{discrepancy_id}", {
        params: { path: { discrepancy_id: f.id } },
        body: { status: next },
      });
      if (error) throw new Error(typeof error.detail === "string" ? humanise(error.detail) : "Could not update");
      return data;
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["discrepancies"] }),
        queryClient.invalidateQueries({ queryKey: ["document", f.document_id] }),
      ]),
  });
  const { icon: Icon, tone } = GROUP_ICON[groupOf(f.type)];
  const open = f.status === "open";

  return (
    <li
      onClick={() => navigate(`/documents/${f.document_id}`)}
      className={clsx(
        "group flex cursor-pointer items-start gap-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card transition hover:border-slate-300 hover:shadow-lift",
        !open && "opacity-75",
      )}
    >
      <span className={clsx("grid size-10 shrink-0 place-items-center rounded-xl", tone)}>
        <Icon className="size-5" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span title={RULES[f.rule]} className="rounded-md bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white">
            {f.rule}
          </span>
          <span className="font-medium">{humanise(f.type)}</span>
          {!open && (
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-[11px] font-medium",
                f.status === "resolved" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600",
              )}
            >
              {humanise(f.status)}
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-600">{f.message}</p>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <DocChip doc={doc} fallback={f.filename} />
          {related && (
            <>
              <span className="text-slate-400">duplicate of</span>
              <DocChip doc={related} fallback={related.filename} />
            </>
          )}
          {f.expected != null && (
            <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-800 ring-1 ring-inset ring-emerald-100">
              expected <b className="tabular">{f.expected}</b>
            </span>
          )}
          {f.actual != null && (
            <span className="rounded-md bg-rose-50 px-2 py-0.5 text-rose-800 ring-1 ring-inset ring-rose-100">
              found <b className="tabular">{f.actual}</b>
            </span>
          )}
        </div>
        {update.isError && <p className="mt-2 text-xs text-rose-600">{update.error.message}</p>}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-3">
        {f.amount_impact != null && (
          <div className="text-right">
            <div className="font-semibold tabular">{formatMoney(f.amount_impact)}</div>
            <div className="text-[11px] text-slate-500">impact</div>
          </div>
        )}
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          {update.isPending ? (
            <Loader2 className="m-1.5 size-4 animate-spin text-slate-400" />
          ) : open ? (
            <>
              <Action label="Resolve" tone="emerald" onClick={() => update.mutate("resolved")}>
                <Check className="size-3.5" /> Resolve
              </Action>
              <Action label="Dismiss: not a real problem" tone="slate" onClick={() => update.mutate("dismissed")}>
                <X className="size-3.5" /> Dismiss
              </Action>
            </>
          ) : (
            <Action label="Reopen: the checks run again" tone="slate" onClick={() => update.mutate("open")}>
              <RotateCcw className="size-3.5" /> Reopen
            </Action>
          )}
          <ChevronRight className="size-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-500" />
        </div>
      </div>
    </li>
  );
}

function DocChip({ doc, fallback }: { doc?: DocumentSummary; fallback: string }) {
  return (
    <span className="inline-flex max-w-72 items-center gap-1.5 truncate rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
      <b className="font-medium">{doc?.number ?? fallback}</b>
      {doc && <span className="truncate text-slate-500">· {[docTypeLabel(doc.doc_type), doc.counterparty].filter(Boolean).join(" · ")}</span>}
    </span>
  );
}

function Action({ label, tone, onClick, children }: { label: string; tone: "emerald" | "slate"; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 ring-inset transition",
        tone === "emerald"
          ? "bg-emerald-50 text-emerald-700 ring-emerald-200 hover:bg-emerald-100"
          : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50",
      )}
    >
      {children}
    </button>
  );
}

function EmptyState({ status }: { status: StatusKey }) {
  const text: Record<StatusKey, [string, string]> = {
    open: ["No open findings", "Every invoice matches its purchase order and delivery note, and all the arithmetic adds up."],
    resolved: ["Nothing resolved yet", "Findings you resolve appear here."],
    dismissed: ["Nothing dismissed", "Findings you dismiss as not a real problem appear here."],
    all: ["No findings", "Upload invoices, purchase orders and delivery notes to run the checks."],
  };
  const [title, body] = text[status];
  return (
    <div className="grid place-items-center rounded-2xl border border-dashed border-slate-300 bg-white/60 px-6 py-16 text-center">
      <span className="grid size-12 place-items-center rounded-2xl bg-emerald-50 text-emerald-600">
        <ShieldCheck className="size-6" />
      </span>
      <p className="mt-4 font-medium">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{body}</p>
    </div>
  );
}
