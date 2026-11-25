import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";

interface Service { name: string; category: string; state: "ok" | "degraded" | "down"; latency_ms: number | null; detail: string }

const STATE = {
  ok: { label: "Operational", color: "var(--ok)", icon: "check" as const },
  degraded: { label: "Degraded", color: "var(--warn)", icon: "alert" as const },
  down: { label: "Down", color: "var(--danger)", icon: "alert" as const },
};

export function ServiceStatus() {
  const [services, setServices] = useState<Service[]>([]);
  const [at, setAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    try {
      setServices((await api<{ services: Service[] }>("/platform/status")).services);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
    setAt(new Date());
  }, []);

  useEffect(() => {
    void check();
    const id = setInterval(check, 60000);
    return () => clearInterval(id);
  }, [check]);

  const count = (s: Service["state"]) => services.filter((x) => x.state === s).length;

  return (
    <>
      <PageHead title="Service status">
        <span className="muted">{at ? `Last check ${at.toLocaleTimeString()} · every 60 s` : "Checking…"}</span>
        <button className="btn spacer" onClick={check}><Icon name="refresh" />Check now</button>
      </PageHead>
      <div className="page-body">
        {error && <div className="error" role="alert">API not reachable: {error}</div>}
        <div className="row" style={{ gap: 12 }}>
          {(["ok", "degraded", "down"] as const).map((s) => (
            <div key={s} className="card" style={{ flex: 1, minWidth: 160, padding: "12px 16px", borderTop: `3px solid ${STATE[s].color}` }}>
              <div className="muted small">{STATE[s].label}</div>
              <strong style={{ fontSize: 22 }}>{count(s)}</strong>
            </div>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Service</th><th>Category</th><th>Status</th><th>Latency</th><th>Detail</th></tr></thead>
            <tbody>
              {services.map((s) => (
                <tr key={s.name}>
                  <td><strong>{s.name}</strong></td>
                  <td className="muted">{s.category}</td>
                  <td><span className="row" style={{ gap: 6, color: STATE[s.state].color }}><Icon name={STATE[s.state].icon} />{STATE[s.state].label}</span></td>
                  <td>{s.latency_ms != null ? `${s.latency_ms} ms` : "—"}</td>
                  <td className="muted">{s.detail || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span className="muted small">Integrations appear here as they are added.</span>
      </div>
    </>
  );
}
