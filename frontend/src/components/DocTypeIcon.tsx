import clsx from "clsx";
import { FileQuestion, FileSignature, FileText, PackageCheck, ShoppingCart } from "lucide-react";

const TYPES = {
  invoice: { icon: FileText, tone: "bg-brand-50 text-brand-600" },
  purchase_order: { icon: ShoppingCart, tone: "bg-sky-50 text-sky-600" },
  delivery_note: { icon: PackageCheck, tone: "bg-teal-50 text-teal-600" },
  other: { icon: FileSignature, tone: "bg-violet-50 text-violet-600" },
} as const;

export function DocTypeIcon({ type, className }: { type: string | null | undefined; className?: string }) {
  const t = TYPES[(type ?? "") as keyof typeof TYPES] ?? { icon: FileQuestion, tone: "bg-slate-100 text-slate-400" };
  const Icon = t.icon;
  return (
    <span className={clsx("grid size-9 shrink-0 place-items-center rounded-lg", t.tone, className)}>
      <Icon className="size-[18px]" aria-hidden />
    </span>
  );
}
