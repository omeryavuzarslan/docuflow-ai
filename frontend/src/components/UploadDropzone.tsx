import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, CopyCheck, FileUp, Loader2, XCircle } from "lucide-react";
import { useRef, useState } from "react";

import { uploadDocument } from "../api/client";

type Item = { id: string; name: string; state: "uploading" | "queued" | "duplicate" | "error"; message?: string };

export function UploadDropzone() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [items, setItems] = useState<Item[]>([]);

  const upload = useMutation({
    mutationFn: async (file: File) => uploadDocument(file),
  });

  function update(id: string, patch: Partial<Item>) {
    setItems((all) => all.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  }

  async function handle(files: FileList | File[]) {
    const pdfs = Array.from(files);
    const added = pdfs.map((f, i) => ({ id: `${Date.now()}-${i}-${f.name}`, name: f.name, state: "uploading" as const }));
    setItems((all) => [...added, ...all].slice(0, 8));
    await Promise.all(
      pdfs.map(async (file, i) => {
        try {
          const { duplicate } = await upload.mutateAsync(file);
          update(added[i].id, { state: duplicate ? "duplicate" : "queued" });
        } catch (error) {
          update(added[i].id, { state: "error", message: (error as Error).message });
        }
      }),
    );
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handle(e.dataTransfer.files);
        }}
        className={clsx(
          "group flex w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-9 text-center transition-all",
          dragging
            ? "border-brand-500 bg-brand-50/70 scale-[1.005]"
            : "border-slate-200 bg-white hover:border-brand-500/60 hover:bg-brand-50/30",
        )}
      >
        <span className="grid size-12 place-items-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 transition-transform group-hover:-translate-y-0.5">
          <FileUp className="size-6" aria-hidden />
        </span>
        <span>
          <span className="block text-sm font-semibold text-slate-800">
            Drop invoices, orders or delivery notes
          </span>
          <span className="mt-1 block text-xs text-slate-500">
            or <span className="font-medium text-brand-600">browse</span> · PDF, up to 20 MB · scans are fine
          </span>
        </span>
        <input
          ref={input}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => e.target.files && void handle(e.target.files)}
        />
      </button>
      {items.length > 0 && (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white text-sm shadow-card">
          {items.map((it) => (
            <li key={it.id} className="flex items-center gap-3 px-4 py-2.5 animate-fade-in">
              {it.state === "uploading" && <Loader2 className="size-4 animate-spin text-brand-500" aria-hidden />}
              {it.state === "queued" && <CheckCircle2 className="size-4 text-emerald-500" aria-hidden />}
              {it.state === "duplicate" && <CopyCheck className="size-4 text-slate-400" aria-hidden />}
              {it.state === "error" && <XCircle className="size-4 text-rose-500" aria-hidden />}
              <span className="flex-1 truncate text-slate-700">{it.name}</span>
              <span className="text-xs text-slate-500">
                {it.state === "uploading" && "Uploading…"}
                {it.state === "queued" && "Queued for processing"}
                {it.state === "duplicate" && "Already uploaded"}
                {it.state === "error" && (it.message ?? "Failed")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
