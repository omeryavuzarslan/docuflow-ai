import clsx from "clsx";
import { Loader2, Maximize2, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { toScreen, type Box } from "../lib/fields";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type Highlight = {
  key: string;
  page: number; // 1-based
  bbox: Box; // PDF points, origin top-left (as the backend stores provenance)
  tone: "active" | "finding";
};

const ZOOMS = [0.75, 1, 1.25, 1.5, 2];

export function PdfViewer({
  bytes,
  highlights,
  focusKey,
}: {
  bytes: Uint8Array;
  highlights: Highlight[];
  focusKey: string | null; // scroll the highlight with this key into view
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [pages, setPages] = useState(0);
  const [pageWidths, setPageWidths] = useState<Record<number, number>>({}); // points
  const [zoom, setZoom] = useState(1);

  // pdf.js takes ownership of the buffer it is given, so hand it a copy.
  const file = useMemo(() => ({ data: bytes.slice() }), [bytes]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // "Fit width" at zoom 1, capped so a wide screen does not blow the page up.
  const pageWidth = Math.max(240, Math.min(containerWidth, 860) * zoom);

  useEffect(() => {
    if (!focusKey) return;
    const target = scroller.current?.querySelector<HTMLElement>(`[data-highlight="${CSS.escape(focusKey)}"]`);
    target?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  }, [focusKey, pageWidths]);

  const zoomIndex = ZOOMS.indexOf(zoom);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200/80 bg-white px-4 text-xs text-slate-500">
        <span className="tabular">{pages ? `${pages} page${pages > 1 ? "s" : ""}` : "Loading…"}</span>
        <div className="flex items-center gap-1">
          <ToolButton label="Zoom out" disabled={zoomIndex <= 0} onClick={() => setZoom(ZOOMS[zoomIndex - 1])}>
            <Minus className="size-3.5" />
          </ToolButton>
          <span className="w-11 text-center font-medium text-slate-600 tabular">{Math.round(zoom * 100)}%</span>
          <ToolButton label="Zoom in" disabled={zoomIndex >= ZOOMS.length - 1} onClick={() => setZoom(ZOOMS[zoomIndex + 1])}>
            <Plus className="size-3.5" />
          </ToolButton>
          <ToolButton label="Fit width" disabled={zoom === 1} onClick={() => setZoom(1)}>
            <Maximize2 className="size-3.5" />
          </ToolButton>
        </div>
      </div>

      <div ref={scroller} className="flex-1 overflow-auto bg-slate-100/80 px-6 py-6">
        <Document
          file={file}
          onLoadSuccess={(pdf) => setPages(pdf.numPages)}
          loading={<Centered><Loader2 className="size-5 animate-spin text-slate-400" /></Centered>}
          error={<Centered>Could not display this PDF.</Centered>}
          className="flex flex-col items-center gap-5"
        >
          {Array.from({ length: pages }, (_, i) => i + 1).map((number) => {
            const scale = pageWidths[number] ? pageWidth / pageWidths[number] : 0;
            return (
              <div key={number} className="relative rounded-sm bg-white shadow-lift ring-1 ring-slate-900/5">
                <Page
                  pageNumber={number}
                  width={pageWidth}
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  onLoadSuccess={(page) =>
                    setPageWidths((w) => ({ ...w, [number]: page.view[2] - page.view[0] }))
                  }
                  loading={<div style={{ width: pageWidth, height: pageWidth * 1.414 }} />}
                />
                {scale > 0 &&
                  highlights
                    .filter((h) => h.page === number)
                    .map((h) => (
                      <div
                        key={h.key}
                        data-highlight={h.key}
                        style={toScreen(h.bbox, scale)}
                        className={clsx(
                          "pointer-events-none absolute rounded-[3px] transition-all duration-200",
                          h.tone === "active"
                            ? "bg-brand-500/15 ring-2 ring-brand-500 animate-fade-in"
                            : "bg-rose-500/10 ring-[1.5px] ring-rose-400/80",
                        )}
                      />
                    ))}
              </div>
            );
          })}
        </Document>
      </div>
    </div>
  );
}

function ToolButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-7 place-items-center rounded-md text-slate-600 hover:bg-slate-100 disabled:opacity-35 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="grid h-64 w-full place-items-center text-sm text-slate-500">{children}</div>;
}
