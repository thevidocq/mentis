import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { PageHead } from "../../layouts/AdminShell";

export interface UsageRow {
  customer: string;
  provider: string;
  questions: number;
  answered: number;
  not_found: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  avg_latency_ms: number | null;
  cost_usd: number | null;
}

export interface UsageData { rows: UsageRow[]; totals: Omit<UsageRow, "customer" | "provider" | "avg_latency_ms"> }

const n = (v: number) => v.toLocaleString();
export const usd = (v: number | null) => (v == null ? "—" : `$${v < 1 ? v.toFixed(4) : v.toFixed(2)}`);

export function useUsage(days: number) {
  const [data, setData] = useState<UsageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    // Switching period quickly: a slower answer for the previous period must not replace this one.
    let stale = false;
    api<UsageData>(`/usage?days=${days}`)
      .then((d) => { if (!stale) { setData(d); setError(null); } })
      .catch((e) => { if (!stale) setError(errorText(e)); });
    return () => { stale = true; };
  }, [days]);
  return { data, error };
}

export function UsageTable({ rows, showCustomer = true, showCost = true }: { rows: UsageRow[]; showCustomer?: boolean; showCost?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{showCustomer && <th>Customer</th>}<th>LLM</th><th>Questions</th><th>Answered</th><th>Not found</th><th>Errors</th><th>Tokens in</th><th>Tokens out</th><th>Avg time</th>{showCost && <th>Est. cost</th>}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={showCustomer ? 10 : 9} className="muted">No questions in this period.</td></tr>}
          {rows.map((r) => (
            <tr key={`${r.customer}|${r.provider}`}>
              {showCustomer && <td><strong>{r.customer}</strong></td>}
              <td>{r.provider === "—" ? <span className="muted">none (not found)</span> : r.provider}</td>
              <td>{n(r.questions)}</td><td>{n(r.answered)}</td><td>{n(r.not_found)}</td>
              <td>{r.errors ? <span className="pill danger">{r.errors}</span> : 0}</td>
              <td>{n(r.input_tokens)}</td><td>{n(r.output_tokens)}</td>
              <td>{r.avg_latency_ms != null ? `${(r.avg_latency_ms / 1000).toFixed(1)} s` : "—"}</td>
              {showCost && <td>{usd(r.cost_usd)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Usage() {
  const [days, setDays] = useState(30);
  const { data, error } = useUsage(days);
  const t = data?.totals;
  return (
    <>
      <PageHead title="LLM usage">
        <span className="spacer" />
        <select className="input" aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last year</option>
        </select>
      </PageHead>
      <div className="page-body">
        {error && <div className="error">{error}</div>}
        {t && (
          <div className="row" style={{ gap: 12 }}>
            {[["Questions", n(t.questions)], ["Answered", n(t.answered)], ["Not found", n(t.not_found)], ["Tokens", n(t.input_tokens + t.output_tokens)], ["Estimated cost", usd(t.cost_usd)]].map(([k, v]) => (
              <div key={k} className="card" style={{ flex: 1, minWidth: 150, padding: "12px 16px" }}>
                <div className="muted small">{k}</div><strong style={{ fontSize: 22 }}>{v}</strong>
              </div>
            ))}
          </div>
        )}
        {data && <UsageTable rows={data.rows} />}
        <span className="muted small">
          From the chat log events, so it follows log retention. "Not found" questions do not call the LLM. The cost uses the prices set on each AI provider (USD per million tokens); without prices it shows —.
        </span>
      </div>
    </>
  );
}
