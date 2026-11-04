import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Clock3, Loader2, XCircle } from "lucide-react";

const STATUS = {
  queued: { label: "Queued", icon: Clock3, tone: "bg-slate-100 text-slate-600 ring-slate-200", spin: false },
  processing: { label: "Processing", icon: Loader2, tone: "bg-brand-50 text-brand-700 ring-brand-100", spin: true },
  done: { label: "Ready", icon: CheckCircle2, tone: "bg-emerald-50 text-emerald-700 ring-emerald-100", spin: false },
  needs_review: { label: "Needs review", icon: AlertTriangle, tone: "bg-amber-50 text-amber-800 ring-amber-200", spin: false },
  failed: { label: "Failed", icon: XCircle, tone: "bg-rose-50 text-rose-700 ring-rose-100", spin: false },
} as const;

export type Status = keyof typeof STATUS;

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status as Status] ?? STATUS.queued;
  const Icon = s.icon;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        s.tone,
      )}
    >
      <Icon className={clsx("size-3.5", s.spin && "animate-spin")} aria-hidden />
      {s.label}
    </span>
  );
}
