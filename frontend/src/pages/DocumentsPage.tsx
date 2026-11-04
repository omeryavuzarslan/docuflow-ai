import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ChevronRight, FileStack, Loader2, Search, ShieldAlert } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api, type Discrepancy, type DocumentSummary } from "../api/client";
import { DocTypeIcon } from "../components/DocTypeIcon";
import { StatusBadge } from "../components/StatusBadge";
import { TopBar } from "../components/TopBar";
import { UploadDropzone } from "../components/UploadDropzone";
import { docTypeLabel, formatMoney, formatRelative, shortName } from "../lib/format";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "attention", label: "Needs attention" },
  { key: "processing", label: "In progress" },
  { key: "done", label: "Ready" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: async () => (await api.GET("/documents", { params: { query: { limit: 500 } } })).data ?? [],
    // Poll while anything is still being processed, so statuses update by themselves.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "queued" || d.status === "processing") ? 2000 : false,
  });
}

function useOpenFindings() {
  return useQuery({
    queryKey: ["discrepancies", "open"],
    queryFn: async () => (await api.GET("/discrepancies", { params: { query: { status: "open" } } })).data ?? [],
  });
}

function Stat({ label, value, icon, tone }: { label: string; value: number | string; icon: ReactNode; tone: string }) {
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

export function DocumentsPage() {
  const navigate = useNavigate();
  const documents = useDocuments();
  const findings = useOpenFindings();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");

  const findingsByDoc = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of findings.data ?? ([] as Discrepancy[])) counts.set(f.document_id, (counts.get(f.document_id) ?? 0) + 1);
    return counts;
  }, [findings.data]);

  const all = documents.data ?? [];
  const attention = (d: DocumentSummary) =>
    d.status === "needs_review" || d.status === "failed" || (findingsByDoc.get(d.id) ?? 0) > 0;
  const visible = all.filter((d) => {
    const haystack = `${d.number ?? ""} ${d.counterparty ?? ""} ${d.filename} ${docTypeLabel(d.doc_type)}`;
    if (search && !haystack.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "attention") return attention(d);
    if (filter === "processing") return d.status === "queued" || d.status === "processing";
    if (filter === "done") return d.status === "done" && !attention(d);
    return true;
  });
  const inProgress = all.filter((d) => d.status === "queued" || d.status === "processing").length;

  return (
    <>
      <TopBar title="Documents" subtitle="Upload, track and review your purchasing documents" />
      <div className="mx-auto max-w-6xl space-y-8 px-8 py-8 animate-fade-in">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Documents" value={all.length} icon={<FileStack className="size-5" />} tone="bg-slate-100 text-slate-600" />
          <Stat label="Open findings" value={findings.data?.length ?? 0} icon={<ShieldAlert className="size-5" />} tone="bg-rose-50 text-rose-600" />
          <Stat
            label="Need review"
            value={all.filter((d) => d.status === "needs_review").length}
            icon={<AlertTriangle className="size-5" />}
            tone="bg-amber-50 text-amber-600"
          />
          <Stat
            label="In progress"
            value={inProgress}
            icon={<Loader2 className={clsx("size-5", inProgress > 0 && "animate-spin")} />}
            tone="bg-brand-50 text-brand-600"
          />
        </div>

        <UploadDropzone />

        <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setFilter(f.key)}
                  className={clsx(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-all",
                    filter === f.key ? "bg-white text-slate-900 shadow-card" : "text-slate-500 hover:text-slate-800",
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
              <Search className="size-4 text-slate-400" aria-hidden />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search number, supplier, file"
                className="w-52 bg-transparent outline-none placeholder:text-slate-400"
              />
            </label>
          </div>

          {documents.isLoading ? (
            <div className="space-y-2 p-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
              <FileStack className="size-8 text-slate-300" aria-hidden />
              <p className="text-sm font-medium text-slate-700">
                {all.length === 0 ? "No documents yet" : "Nothing matches this view"}
              </p>
              <p className="text-xs text-slate-500">
                {all.length === 0 ? "Upload a PDF above to get started." : "Try another filter or search."}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-400">
                  <th className="px-5 py-3 font-medium">Document</th>
                  <th className="px-3 py-3 text-right font-medium">Amount</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">Findings</th>
                  <th className="px-3 py-3 font-medium">Uploaded</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((d) => {
                  const count = findingsByDoc.get(d.id) ?? 0;
                  return (
                    <tr
                      key={d.id}
                      onClick={() => navigate(`/documents/${d.id}`)}
                      className="group cursor-pointer transition-colors hover:bg-slate-50/80"
                    >
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <DocTypeIcon type={d.doc_type} />
                          <div className="min-w-0">
                            <div className="truncate font-medium text-slate-800 tabular">
                              {d.number ?? shortName(d.filename)}
                            </div>
                            <div className="truncate text-xs text-slate-500">
                              {docTypeLabel(d.doc_type)}
                              {d.counterparty && <span className="text-slate-400"> · {d.counterparty}</span>}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right font-medium text-slate-700 tabular">
                        {d.amount != null ? formatMoney(String(d.amount)) : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-3 py-3">
                        <StatusBadge status={d.status} />
                      </td>
                      <td className="px-3 py-3">
                        {count > 0 ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700 ring-1 ring-inset ring-rose-100">
                            <ShieldAlert className="size-3.5" aria-hidden /> {count}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500 tabular">{formatRelative(d.created_at)}</td>
                      <td className="pr-4 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-500">
                        <ChevronRight className="size-4" aria-hidden />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}
