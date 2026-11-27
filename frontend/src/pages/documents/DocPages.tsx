import type { DocPage, DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";
import { isBusy } from "./status";

const FLAG_LABEL: Record<string, string> = {
  empty: "No text", low_confidence: "Low OCR confidence", merged_cells: "Merged cells", truncated: "Truncated",
};

interface Props {
  base: string;
  shown: DocVersion;
  pages: DocPage[];
  current: number | null;
  onPage: (index: number) => void;
  mode: "preview" | "text";
  onRetry: () => void;
}

/** One page at a time: the original (preview) or the text read, with page navigation and quality flags. */
export function DocPages({ base, shown, pages, current, onPage, mode, onRetry }: Props) {
  if (shown.status !== "ready") return <NotReady v={shown} onRetry={onRetry} />;
  const pageIdx = pages.findIndex((p) => p.index === current);
  const page = pages[pageIdx] ?? null;
  return (
    <>
      <div className="doc-pagebar">
        <button className="icon-btn" style={{ border: 0 }} aria-label="Previous page" disabled={pageIdx <= 0} onClick={() => onPage(pages[pageIdx - 1].index)}><Icon name="chevronLeft" /></button>
        <span>{page ? <>{page.label} <span className="doc-pagecount">{pageIdx + 1} / {pages.length}</span></> : "…"}</span>
        <button className="icon-btn" style={{ border: 0 }} aria-label="Next page" disabled={pageIdx < 0 || pageIdx >= pages.length - 1} onClick={() => onPage(pages[pageIdx + 1].index)}><Icon name="chevronRight" /></button>
        {page && mode === "text" && <>
          <span className="doc-pagebar-sep" />
          <span>{page.method === "ocr" ? `OCR${page.ocr_confidence != null ? ` ${Math.round(page.ocr_confidence * 100)}%` : ""}` : "Native text"}</span>
          {page.tables > 0 && <span>{page.tables} {page.tables === 1 ? "table" : "tables"}</span>}
        </>}
        {page?.flags.map((f) => <span key={f} className="doc-flag"><Icon name="alert" size={13} />{FLAG_LABEL[f] ?? f}</span>)}
      </div>
      <div className="doc-stage">
        {page && mode === "preview" && page.has_image && (
          <img className="doc-page-img" src={`/api${base}/versions/${shown.id}/pages/${page.index}/image`} alt={`${page.label} of the original`} />
        )}
        {page && (mode === "text" || !page.has_image) && (
          <article className="doc-page-text">
            {page.text ? <Markdown source={page.text} breaks /> : <p className="muted" style={{ margin: 0 }}>No text was found on this {page.kind}.</p>}
          </article>
        )}
      </div>
    </>
  );
}

function NotReady({ v, onRetry }: { v: DocVersion; onRetry: () => void }) {
  return (
    <div className="doc-pad doc-notready">
      {isBusy(v) && <><span className="dots"><i /><i /><i /></span><p>Reading and indexing v{v.version}… The preview appears when it is done.</p></>}
      {v.status === "failed" && <>
        <span style={{ color: "var(--danger)" }}><Icon name="alert" size={22} /></span>
        <p><strong>Processing of v{v.version} failed.</strong><br /><span className="muted">{v.error ?? "Unknown error."}</span></p>
        <button className="btn" onClick={onRetry}><Icon name="refresh" />Retry</button>
      </>}
    </div>
  );
}
