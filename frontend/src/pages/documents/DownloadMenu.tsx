import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { Icon } from "../../components/Icon";

export type ExportFormat = "original" | "md" | "json";

const LABELS: Record<ExportFormat, [string, string]> = {
  original: ["Original", "The file as uploaded"],
  md: ["Markdown (.md)", "The text Mentis read, page by page"],
  json: ["JSON", "Text, pages and indexed passages, to import elsewhere"],
};

/** Downloads a file from the API; errors (409, 413, 503...) are shown instead of a raw JSON page. */
export async function download(path: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Mentis cannot be reached. Check your connection and try again.");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : `Download failed (${res.status}).`;
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const utf = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  const plain = /filename="([^"]+)"/i.exec(cd);
  const name = utf ? decodeURIComponent(utf[1]) : plain ? plain[1] : "download";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/**
 * The download button with its format menu. `paths` gives the API path of each format;
 * a format without a path is shown disabled with `unavailable` as the reason.
 */
export function DownloadMenu({ paths, label, title, unavailable, onError, compact = false }: {
  paths: Partial<Record<ExportFormat, string>>;
  label?: string;
  title: string;
  unavailable?: string;
  onError: (message: string | null) => void; // null: a new download started, clear the last error
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); setOpen(false); } };
    window.addEventListener("click", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("click", close); window.removeEventListener("keydown", esc); };
  }, [open]);

  async function pick(f: ExportFormat) {
    const path = paths[f];
    setOpen(false);
    if (!path || busy) return;
    setBusy(f);
    onError(null);
    try {
      await download(path);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="menu-wrap">
      <button type="button" className={label ? `btn${compact ? " btn-sm" : ""}` : "icon-btn"} aria-haspopup="menu" aria-expanded={open}
        aria-label={label ? undefined : title} title={title} disabled={!!busy}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}>
        <Icon name="download" />{label}{busy && <span className="muted small">…</span>}
      </button>
      {open && (
        <div className="menu" role="menu" onClick={(e) => e.stopPropagation()}>
          {(Object.keys(LABELS) as ExportFormat[]).map((f) => (
            <button key={f} type="button" role="menuitem" disabled={!paths[f]} title={!paths[f] ? unavailable : undefined} onClick={() => pick(f)}>
              <Icon name={f === "original" ? "file" : f === "md" ? "list" : "database"} />
              <span className="stack" style={{ gap: 0 }}>
                <span>{LABELS[f][0]}</span>
                <span className="muted small">{!paths[f] && unavailable ? unavailable : LABELS[f][1]}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
