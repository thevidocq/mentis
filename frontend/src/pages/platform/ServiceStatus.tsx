import { useCallback, useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";

interface Health { status: string; version: string; database: string }

// First version: API and database. Workers, Qdrant, MinIO, embeddings, LLMs and integrations join as they ship.
export function ServiceStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const [failed, setFailed] = useState(false);

  const check = useCallback(async () => {
    const t0 = performance.now();
    try {
      const r = await fetch("/api/health");
      setHealth(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
    }
    setMs(Math.round(performance.now() - t0));
    setAt(new Date());
  }, []);

  useEffect(() => {
    void check();
    const id = setInterval(check, 60000);
    return () => clearInterval(id);
  }, [check]);

  const rows = [
    { name: "API backend", ok: !failed && !!health, detail: health ? `v${health.version}` : "unreachable", latency: ms },
    { name: "PostgreSQL", ok: health?.database === "ok", detail: health?.database ?? "—", latency: null },
  ];

  return (
    <>
      <PageHead title="Service status">
        <span className="muted">{at ? `Last check ${at.toLocaleTimeString()} · every 60 s` : "Checking…"}</span>
        <button className="btn spacer" onClick={check}><Icon name="refresh" />Check now</button>
      </PageHead>
      <div className="page-body">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Service</th><th>Status</th><th>Latency</th><th>Detail</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name}>
                  <td><strong>{r.name}</strong></td>
                  <td>
                    <span className="row" style={{ gap: 6, color: r.ok ? "var(--ok)" : "var(--danger)" }}>
                      <Icon name={r.ok ? "check" : "alert"} />{r.ok ? "Operational" : "Down"}
                    </span>
                  </td>
                  <td>{r.latency != null ? `${r.latency} ms` : "—"}</td>
                  <td className="muted">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span className="muted small">Qdrant, MinIO, workers, embeddings, LLM providers and integrations appear here as they are added.</span>
      </div>
    </>
  );
}
