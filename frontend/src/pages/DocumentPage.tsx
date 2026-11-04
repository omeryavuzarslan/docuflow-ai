import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CircleAlert,
  Download,
  FileSearch,
  History,
  Loader2,
  MapPin,
  Pencil,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { api, apiOwner, type Discrepancy, type DocumentDetail } from "../api/client";
import { DocTypeIcon } from "../components/DocTypeIcon";
import { PdfViewer, type Highlight } from "../components/PdfViewer";
import { StatusBadge } from "../components/StatusBadge";
import { allFields, buildFields, findingPath, LINE_COLUMNS, type FieldView } from "../lib/fields";
import { docTypeLabel, formatMoney, formatRelative, humanise } from "../lib/format";
import { useOwner } from "../lib/owner";

function useDocument(id: string) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/documents/{document_id}", { params: { path: { document_id: id } } });
      if (error) throw new Error("not found");
      return data;
    },
    refetchInterval: (q) => (["queued", "processing"].includes(q.state.data?.status ?? "") ? 2000 : false),
  });
}

function useFile(id: string) {
  return useQuery({
    queryKey: ["document-file", id],
    queryFn: async () => {
      const response = await fetch(`/api/documents/${id}/file`, { headers: { "X-Owner-Id": apiOwner() } });
      if (!response.ok) throw new Error("file not available");
      return new Uint8Array(await response.arrayBuffer());
    },
    staleTime: Infinity,
  });
}

export function DocumentPage() {
  const { id = "" } = useParams();
  const doc = useDocument(id);
  const file = useFile(id);
  const [active, setActive] = useState<string | null>(null); // clicked field path
  const [hover, setHover] = useState<string | null>(null);

  const extraction = doc.data?.extraction;
  const sections = useMemo(
    () =>
      extraction
        ? buildFields(
            extraction.raw,
            extraction.provenance,
            extraction.conversion_errors,
            doc.data?.corrections ?? [],
          )
        : null,
    [extraction, doc.data?.corrections],
  );
  const fields = useMemo(() => (sections ? allFields(sections) : []), [sections]);
  const byPath = useMemo(() => new Map(fields.map((f) => [f.path, f])), [fields]);
  const findings = doc.data?.discrepancies ?? [];
  const openFindings = findings.filter((f) => f.status === "open");
  const flagged = new Set(openFindings.map((f) => findingPath(f.field)).filter((p): p is string => !!p));

  const highlights: Highlight[] = useMemo(() => {
    const out: Highlight[] = [];
    for (const f of openFindings) {
      const loc = byPath.get(findingPath(f.field) ?? "")?.location;
      if (loc) out.push({ key: `finding:${f.id}`, ...loc, tone: "finding" });
    }
    const shown = hover ?? active;
    const loc = shown ? byPath.get(shown)?.location : null;
    if (shown && loc) out.push({ key: shown, ...loc, tone: "active" });
    return out;
  }, [openFindings, byPath, hover, active]);

  if (doc.isLoading) return <FullPage><Loader2 className="size-6 animate-spin text-slate-400" /></FullPage>;
  if (doc.isError || !doc.data)
    return (
      <FullPage>
        <div className="text-center">
          <p className="font-medium">Document not found</p>
          <Link to="/documents" className="mt-2 inline-block text-sm text-brand-600 hover:underline">
            Back to documents
          </Link>
        </div>
      </FullPage>
    );

  const d = doc.data;
  const select = (path: string | null) => setActive((current) => (current === path ? null : path));

  return (
    <div className="flex h-full flex-col">
      <Header doc={d} />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.15fr)_minmax(420px,1fr)]">
        <section className="hidden min-h-0 border-r border-slate-200/80 lg:block">
          {file.data ? (
            <PdfViewer bytes={file.data} highlights={highlights} focusKey={active} />
          ) : (
            <FullPage>
              {file.isError ? (
                <span className="text-sm text-slate-500">The original file is not available.</span>
              ) : (
                <Loader2 className="size-5 animate-spin text-slate-400" />
              )}
            </FullPage>
          )}
        </section>

        <section className="min-h-0 overflow-y-auto">
          <div className="space-y-5 p-6">
            {d.status === "needs_review" && <ReviewBanner fields={fields} />}
            {(d.status === "queued" || d.status === "processing") && (
              <Banner tone="brand" icon={<Loader2 className="size-4 animate-spin" />}>
                Reading this document… the fields appear here when it is done.
              </Banner>
            )}
            {d.status === "failed" && (
              <Banner tone="rose" icon={<CircleAlert className="size-4" />}>
                Processing failed. Upload the file again to retry.
              </Banner>
            )}

            {findings.length > 0 && (
              <FindingsCard findings={findings} byPath={byPath} onSelect={(path) => path && select(path)} />
            )}

            {d.doc_type === "other" ? (
              <Card>
                <div className="flex items-start gap-3 p-5">
                  <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600">
                    <FileSearch className="size-4.5" />
                  </span>
                  <div className="text-sm">
                    <p className="font-medium">Supplier agreement</p>
                    <p className="mt-1 text-slate-500">
                      Agreements have no fields to check. Their clauses are indexed for search, so you can ask
                      about payment terms, prices and minimum orders in Ask.
                    </p>
                    <Link to="/ask" className="mt-3 inline-block font-medium text-brand-600 hover:underline">
                      Ask about this agreement →
                    </Link>
                  </div>
                </div>
              </Card>
            ) : (
              sections && (
                <>
                  <FieldSummary fields={fields} />
                  <FieldGroup title="Details">
                    <FieldGrid fields={sections.header} id={id} {...{ active, select, setHover, flagged }} />
                  </FieldGroup>
                  <div className="grid gap-5 xl:grid-cols-2">
                    <FieldGroup title="Supplier">
                      <FieldGrid fields={sections.supplier} id={id} cols={1} {...{ active, select, setHover, flagged }} />
                    </FieldGroup>
                    <FieldGroup title="Buyer">
                      <FieldGrid fields={sections.buyer} id={id} cols={1} {...{ active, select, setHover, flagged }} />
                    </FieldGroup>
                  </div>
                  <FieldGroup title={`Line items · ${sections.lines.length}`} flush>
                    <LinesTable sections={sections} id={id} {...{ active, select, setHover, flagged }} />
                  </FieldGroup>
                  <FieldGroup title="Totals">
                    <FieldGrid fields={sections.totals} id={id} {...{ active, select, setHover, flagged }} />
                  </FieldGroup>
                </>
              )
            )}

            {d.corrections.length > 0 && <CorrectionsCard doc={d} />}
            {extraction && (
              <p className="pb-2 text-center text-[11px] text-slate-400">
                Extracted by {extraction.model} · prompt {extraction.prompt_version} · version {extraction.version}
                {extraction.cached ? " · from cache" : ""}
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ---------- header ---------- */

function Header({ doc }: { doc: DocumentDetail }) {
  const title = doc.number ?? doc.filename;
  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-200/80 bg-white/80 px-6 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <Link
          to="/documents"
          title="Back to documents"
          className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <DocTypeIcon type={doc.doc_type} />
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="truncate text-lg font-semibold tracking-tight">{title}</h1>
            <StatusBadge status={doc.status} />
          </div>
          <p className="truncate text-xs text-slate-500">
            {[docTypeLabel(doc.doc_type), doc.counterparty, doc.number ? doc.filename : null, `uploaded ${formatRelative(doc.created_at)}`]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        {doc.amount != null && (
          <div className="text-right">
            <div className="text-lg font-semibold tracking-tight tabular">{formatMoney(doc.amount)}</div>
            <div className="text-[11px] text-slate-500">{doc.doc_type === "invoice" ? "Gross total" : "Net total"}</div>
          </div>
        )}
        <a
          href={`/api/documents/${doc.id}/file`}
          onClick={(e) => {
            // The file needs the owner header, so download through fetch.
            e.preventDefault();
            void downloadFile(doc.id, doc.filename);
          }}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-card hover:bg-slate-50"
        >
          <Download className="size-4" /> PDF
        </a>
      </div>
    </header>
  );
}

async function downloadFile(id: string, filename: string) {
  const response = await fetch(`/api/documents/${id}/file`, { headers: { "X-Owner-Id": apiOwner() } });
  if (!response.ok) return;
  const url = URL.createObjectURL(await response.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/* ---------- banners and summary ---------- */

function Banner({ tone, icon, children }: { tone: "amber" | "rose" | "brand"; icon: ReactNode; children: ReactNode }) {
  return (
    <div
      className={clsx(
        "flex items-start gap-3 rounded-xl px-4 py-3 text-sm ring-1 ring-inset animate-fade-in",
        tone === "amber" && "bg-amber-50 text-amber-900 ring-amber-200",
        tone === "rose" && "bg-rose-50 text-rose-900 ring-rose-200",
        tone === "brand" && "bg-brand-50 text-brand-700 ring-brand-100",
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div>{children}</div>
    </div>
  );
}

function ReviewBanner({ fields }: { fields: FieldView[] }) {
  const errors = fields.filter((f) => f.issue?.kind === "error").length;
  return (
    <Banner tone="amber" icon={<AlertTriangle className="size-4" />}>
      <p className="font-medium">This document needs review</p>
      <p className="mt-0.5 text-amber-800/90">
        {errors > 0
          ? `${errors} field${errors > 1 ? "s" : ""} could not be read. Correct ${errors > 1 ? "them" : "it"} and the checks run again.`
          : "Some fields could not be read. Correct them and the checks run again."}{" "}
        Until then, checks that depend on this document are on hold.
      </p>
    </Banner>
  );
}

function FieldSummary({ fields }: { fields: FieldView[] }) {
  const located = fields.filter((f) => f.location).length;
  const toCheck = fields.filter((f) => f.issue).length;
  const corrected = fields.filter((f) => f.corrected).length;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Pill icon={<MapPin className="size-3.5" />} tone="slate">
        <b className="tabular">{located}</b> values located on the page
      </Pill>
      {toCheck > 0 ? (
        <Pill icon={<AlertTriangle className="size-3.5" />} tone="amber">
          <b className="tabular">{toCheck}</b> to check
        </Pill>
      ) : (
        <Pill icon={<ShieldCheck className="size-3.5" />} tone="emerald">
          Every value verified
        </Pill>
      )}
      {corrected > 0 && (
        <Pill icon={<Pencil className="size-3.5" />} tone="brand">
          <b className="tabular">{corrected}</b> corrected
        </Pill>
      )}
      <span className="ml-auto text-slate-400">Hover a field to see it on the PDF</span>
    </div>
  );
}

function Pill({ icon, tone, children }: { icon: ReactNode; tone: "slate" | "amber" | "emerald" | "brand"; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium ring-1 ring-inset",
        tone === "slate" && "bg-white text-slate-600 ring-slate-200",
        tone === "amber" && "bg-amber-50 text-amber-800 ring-amber-200",
        tone === "emerald" && "bg-emerald-50 text-emerald-700 ring-emerald-100",
        tone === "brand" && "bg-brand-50 text-brand-700 ring-brand-100",
      )}
    >
      {icon}
      <span>{children}</span>
    </span>
  );
}

/* ---------- findings ---------- */

function FindingsCard({
  findings,
  byPath,
  onSelect,
}: {
  findings: Discrepancy[];
  byPath: Map<string, FieldView>;
  onSelect: (path: string | null) => void;
}) {
  const open = findings.filter((f) => f.status === "open");
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert className="size-4 text-rose-500" />
          Findings
          <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700 tabular">{open.length} open</span>
        </h2>
        <Link to="/findings" className="text-xs font-medium text-brand-600 hover:underline">
          All findings
        </Link>
      </div>
      <ul className="divide-y divide-slate-100">
        {findings.map((f) => {
          const path = findingPath(f.field);
          const field = path ? byPath.get(path) : undefined;
          return (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => onSelect(path)}
                disabled={!field?.location}
                className={clsx(
                  "flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors enabled:hover:bg-slate-50",
                  f.status !== "open" && "opacity-60",
                )}
              >
                <span className="mt-0.5 rounded-md bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white">
                  {f.rule}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{humanise(f.type)}</span>
                    {f.status !== "open" && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{f.status}</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[13px] leading-snug text-slate-600">{f.message}</p>
                  {(f.expected != null || f.actual != null) && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-800 ring-1 ring-inset ring-emerald-100">
                        expected <b className="tabular">{f.expected}</b>
                      </span>
                      <span className="rounded-md bg-rose-50 px-2 py-0.5 text-rose-800 ring-1 ring-inset ring-rose-100">
                        found <b className="tabular">{f.actual}</b>
                      </span>
                      {f.amount_impact != null && (
                        <span className="text-slate-500">
                          impact <b className="text-slate-700 tabular">{formatMoney(f.amount_impact)}</b>
                        </span>
                      )}
                    </div>
                  )}
                  {f.related_document_id && (
                    <Link
                      to={`/documents/${f.related_document_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="mt-2 inline-block text-xs font-medium text-brand-600 hover:underline"
                    >
                      Open the related document →
                    </Link>
                  )}
                </div>
                {field?.location && <MapPin className="mt-1 size-3.5 shrink-0 text-slate-400" aria-label="Show on PDF" />}
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/* ---------- fields ---------- */

type FieldProps = {
  id: string;
  flagged: Set<string>; // paths with an open finding
  active: string | null;
  select: (path: string) => void;
  setHover: (path: string | null) => void;
};

function Card({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-card">{children}</div>;
}

function FieldGroup({ title, flush, children }: { title: string; flush?: boolean; children: ReactNode }) {
  return (
    <Card>
      <h2 className="border-b border-slate-100 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </h2>
      <div className={flush ? "" : "p-2"}>{children}</div>
    </Card>
  );
}

function FieldGrid({ fields, cols = 2, ...props }: FieldProps & { fields: FieldView[]; cols?: 1 | 2 }) {
  // Hide optional fields that are empty and were never filled (e.g. address line 2).
  const shown = fields.filter((f) => f.value || f.issue || !f.path.endsWith("address_line2"));
  return (
    <div className={clsx("grid gap-1", cols === 2 && "sm:grid-cols-2")}>
      {shown.map((f) => (
        <FieldCell key={f.path} field={f} {...props} />
      ))}
    </div>
  );
}

function FieldCell({ field, id, active, select, setHover, flagged }: FieldProps & { field: FieldView }) {
  const [editing, setEditing] = useState(false);
  const isActive = active === field.path;
  return (
    <div
      onMouseEnter={() => setHover(field.path)}
      onMouseLeave={() => setHover(null)}
      onClick={() => !editing && field.location && select(field.path)}
      className={clsx(
        "group relative rounded-xl px-3 py-2.5 transition-colors",
        field.location && !editing && "cursor-pointer",
        isActive ? "bg-brand-50 ring-1 ring-inset ring-brand-200" : "hover:bg-slate-50",
        (field.issue?.kind === "error" || flagged.has(field.path)) && !isActive && "bg-rose-50/70 ring-1 ring-inset ring-rose-200",
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
        {field.label}
        <IssueIcon field={field} />
      </div>
      {editing ? (
        <CorrectionEditor field={field} documentId={id} onDone={() => setEditing(false)} />
      ) : (
        <div className="flex items-center gap-2">
          <span className={clsx("min-w-0 flex-1 truncate text-sm tabular", field.value ? "text-slate-900" : "text-slate-300")}>
            {field.value || "—"}
          </span>
          {field.corrected && <CorrectedTag raw={field.raw} />}
          <EditButton onClick={() => setEditing(true)} />
        </div>
      )}
    </div>
  );
}

function IssueIcon({ field }: { field: FieldView }) {
  if (!field.issue) return null;
  return (
    <span title={field.issue.message} className="inline-flex">
      {field.issue.kind === "error" ? (
        <CircleAlert className="size-3.5 text-rose-500" aria-label={field.issue.message} />
      ) : (
        <AlertTriangle className="size-3.5 text-amber-500" aria-label={field.issue.message} />
      )}
    </span>
  );
}

function CorrectedTag({ raw }: { raw: string }) {
  return (
    <span
      title={`Extracted value: ${raw || "(empty)"}`}
      className="shrink-0 rounded-full bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700"
    >
      Edited
    </span>
  );
}

function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      title="Correct this value"
      aria-label="Correct this value"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="grid size-6 shrink-0 place-items-center rounded-md text-slate-400 opacity-0 transition hover:bg-white hover:text-brand-600 hover:shadow-card focus:opacity-100 group-hover:opacity-100"
    >
      <Pencil className="size-3.5" />
    </button>
  );
}

function CorrectionEditor({ field, documentId, onDone }: { field: FieldView; documentId: string; onDone: () => void }) {
  const { owner } = useOwner();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(field.value);
  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/documents/{document_id}/corrections", {
        params: { path: { document_id: documentId } },
        body: { field: field.path, new_value: value.trim(), author: owner },
      });
      if (error) throw new Error(typeof error.detail === "string" ? error.detail : "Could not save the correction");
      return data;
    },
    onSuccess: async () => {
      // A correction rebuilds the document and re-runs the checks: refresh everything it touches.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["document", documentId] }),
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
        queryClient.invalidateQueries({ queryKey: ["discrepancies"] }),
      ]);
      onDone();
    },
  });
  const unchanged = value.trim() === field.value;

  return (
    <form
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault();
        if (unchanged) onDone();
        else save.mutate();
      }}
      className="mt-1"
    >
      <div className="flex items-center gap-1.5">
        <input
          autoFocus
          aria-label={`New value for ${field.label}`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onDone()}
          className="min-w-0 flex-1 rounded-lg border border-brand-300 bg-white px-2.5 py-1.5 text-sm shadow-card outline-none ring-4 ring-brand-100 tabular"
        />
        <button
          type="submit"
          disabled={save.isPending}
          title="Save"
          aria-label="Save"
          className="grid size-8 place-items-center rounded-lg bg-brand-600 text-white shadow-card hover:bg-brand-700 disabled:opacity-60"
        >
          {save.isPending ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
        </button>
        <button
          type="button"
          onClick={onDone}
          title="Cancel"
          aria-label="Cancel"
          className="grid size-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100"
        >
          <X className="size-4" />
        </button>
      </div>
      {save.isError ? (
        <p className="mt-1.5 text-xs text-rose-600">{save.error.message}</p>
      ) : (
        <p className="mt-1.5 text-[11px] text-slate-400">Type it as printed. The extracted value is kept.</p>
      )}
    </form>
  );
}

function LinesTable({ sections, id, active, select, setHover, flagged }: FieldProps & { sections: NonNullable<ReturnType<typeof buildFields>> }) {
  const [editing, setEditing] = useState<string | null>(null);
  if (sections.lines.length === 0) return <p className="px-5 py-4 text-sm text-slate-400">No line items.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] font-medium text-slate-500">
            <th className="py-2 pl-5 pr-2 font-medium">#</th>
            {LINE_COLUMNS.map(([key, label]) => (
              <th key={key} className={clsx("whitespace-nowrap px-2 py-2 font-medium", key !== "sku" && key !== "description" && "text-right")}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sections.lines.map((line) => (
            <tr key={line.index} className="border-t border-slate-100">
              <td className="py-2 pl-5 pr-2 text-xs text-slate-400 tabular">{line.index + 1}</td>
              {LINE_COLUMNS.map(([key]) => {
                const f = line.cells[key];
                const numeric = key !== "sku" && key !== "description";
                if (editing === f.path)
                  return (
                    <td key={key} colSpan={1} className="px-1 py-1 align-top">
                      <div className="min-w-44">
                        <CorrectionEditor field={f} documentId={id} onDone={() => setEditing(null)} />
                      </div>
                    </td>
                  );
                return (
                  <td
                    key={key}
                    onMouseEnter={() => setHover(f.path)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => f.location && select(f.path)}
                    onDoubleClick={() => setEditing(f.path)}
                    title={f.issue?.message ?? (f.corrected ? `Extracted value: ${f.raw}` : "Double-click to correct")}
                    className={clsx(
                      "group px-2 py-2 transition-colors",
                      "whitespace-nowrap",
                      numeric && "text-right tabular",
                      f.location && "cursor-pointer",
                      active === f.path ? "bg-brand-50 text-brand-800" : "hover:bg-slate-50",
                      (f.issue?.kind === "error" || flagged.has(f.path)) &&
                        "bg-rose-50 font-semibold text-rose-700 ring-1 ring-inset ring-rose-200",
                      f.issue?.kind === "unverified" && "text-amber-700",
                      key === "sku" && "font-mono text-xs",
                    )}
                  >
                    <span
                      className={clsx(
                        "items-center gap-1",
                        key === "description" ? "block max-w-40 truncate" : "inline-flex",
                      )}
                    >
                      {f.issue && <IssueIcon field={f} />}
                      {f.value || <span className="text-slate-300">—</span>}
                      {f.corrected && <span className="size-1.5 rounded-full bg-brand-500" aria-label="corrected" />}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-slate-100 px-5 py-2 text-[11px] text-slate-400">Double-click a cell to correct it.</p>
    </div>
  );
}

/* ---------- history ---------- */

function CorrectionsCard({ doc }: { doc: DocumentDetail }) {
  return (
    <Card>
      <h2 className="flex items-center gap-2 border-b border-slate-100 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        <History className="size-3.5" /> Corrections
      </h2>
      <ol className="divide-y divide-slate-100">
        {[...doc.corrections].reverse().map((c) => (
          <li key={c.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{c.field}</code>
            <span className="min-w-0 flex-1 truncate tabular">
              <span className="text-slate-400 line-through">{c.old_value || "(empty)"}</span>
              <span className="mx-1.5 text-slate-300">→</span>
              <span className="font-medium">{c.new_value || "(empty)"}</span>
            </span>
            <span className="shrink-0 text-xs text-slate-400">
              {c.author} · {formatRelative(c.created_at)}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function FullPage({ children }: { children: ReactNode }) {
  return <div className="grid h-full place-items-center">{children}</div>;
}
