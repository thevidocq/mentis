import { useMemo, useState } from "react";
import type { DocSummary } from "../../api/types";
import { Icon } from "../../components/Icon";
import { isBusy, unitText } from "./status";

type Filter = "all" | "in_use" | "review";

/** What a document needs from its admin, if anything (shown as a quiet badge). */
export function attention(d: DocSummary): { label: string; tone: "fail" | "warn" | "run" } | null {
  const v = d.latest;
  if (v.status === "failed") return { label: "Failed", tone: "fail" };
  if (isBusy(v)) return { label: "Processing", tone: "run" };
  if (v.approval === "pending") return { label: "To approve", tone: "warn" };
  return null;
}

function meta(d: DocSummary): string {
  const v = d.active ?? d.latest;
  const pages = v.stats?.pages ? ` · ${unitText(v.file_type, v.stats.pages)}` : "";
  return d.active ? `v${v.version}${pages}` : `v${d.latest.version} · ${new Date(d.latest.uploaded_at).toLocaleDateString()}`;
}

export function DocList({ docs, selected, onSelect }: { docs: DocSummary[]; selected: string | null; onSelect: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const review = docs.filter((d) => attention(d)).length;

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const shown = docs.filter((d) => !needle || d.name.toLowerCase().includes(needle))
      .sort((a, b) => a.name.localeCompare(b.name));
    const need = shown.filter((d) => attention(d));
    const inUse = shown.filter((d) => !attention(d) && d.active);
    const other = shown.filter((d) => !attention(d) && !d.active);
    const out: { label: string; items: DocSummary[] }[] = [];
    if (filter !== "in_use" && need.length) out.push({ label: "Needs attention", items: need });
    if (filter !== "review" && inUse.length) out.push({ label: "In use", items: inUse });
    if (filter === "all" && other.length) out.push({ label: "Not in use", items: other });
    return out;
  }, [docs, q, filter]);

  return (
    <>
      <label className="doc-search">
        <Icon name="search" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search documents" aria-label="Search documents" />
      </label>
      <div className="doc-filter" role="tablist" aria-label="Filter documents">
        {([["all", "All"], ["in_use", "In use"], ["review", `To review${review ? ` · ${review}` : ""}`]] as [Filter, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{label}</button>
        ))}
      </div>
      <div className="doc-items">
        {groups.length === 0 && <p className="muted small doc-empty">{docs.length ? "No document matches." : "No documents yet. Upload procedures, escalation matrices and runbooks."}</p>}
        {groups.map((g) => (
          <section key={g.label} aria-label={g.label}>
            <div className="doc-group">{g.label}</div>
            {g.items.map((d) => {
              const a = attention(d);
              return (
                <button key={d.id} className={`doc-item${d.id === selected ? " on" : ""}`} aria-current={d.id === selected} onClick={() => onSelect(d.id)}>
                  <Icon name="file" />
                  <span className="doc-item-text">
                    <span className="doc-item-name">{d.name}</span>
                    <span className="doc-item-meta">{meta(d)}</span>
                  </span>
                  {a && <span className={`doc-badge ${a.tone}`}>{a.label}</span>}
                </button>
              );
            })}
          </section>
        ))}
      </div>
    </>
  );
}
