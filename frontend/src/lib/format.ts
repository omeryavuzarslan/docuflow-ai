export const DOC_TYPE_LABEL: Record<string, string> = {
  invoice: "Invoice",
  purchase_order: "Purchase order",
  delivery_note: "Delivery note",
  other: "Agreement",
};

export function docTypeLabel(type: string | null | undefined): string {
  return type ? (DOC_TYPE_LABEL[type] ?? "Document") : "Detecting…";
}

/** Money arrives from the API as a decimal string; it is formatted, never converted to float math. */
export function formatMoney(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}£${grouped}.${(fraction + "00").slice(0, 2)}`;
}

export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return then.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function shortName(filename: string): string {
  return filename.split("/").pop() ?? filename;
}

/** "quantity_mismatch" -> "Quantity mismatch" */
export function humanise(text: string) {
  const s = text.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
