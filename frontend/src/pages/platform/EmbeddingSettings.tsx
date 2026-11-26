import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";

interface Reindex { status: "queued" | "running" | "done" | "failed"; done?: number; total?: number; error?: string | null; finished_at?: string }
interface EmbeddingState {
  url: string;
  model: string;
  api_key_set: boolean;
  indexed_model: string | null;
  indexed_dim: number | null;
  reindex_needed: boolean;
  reindex: Reindex | null;
  index: { collections: number; points: number } | null;
}

export function EmbeddingSettings() {
  const [state, setState] = useState<EmbeddingState | null>(null);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api<EmbeddingState>("/platform/embedding");
      setState(s);
      return s;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      return null;
    }
  }, []);

  useEffect(() => {
    void load().then((s) => { if (s) { setUrl(s.url); setModel(s.model); } });
  }, [load]);

  const running = state?.reindex?.status === "queued" || state?.reindex?.status === "running";
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => void load(), 3000);
    return () => clearInterval(id);
  }, [running, load]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, string> = { url, model };
      if (apiKey) body.api_key = apiKey;
      await api("/platform/embedding", { method: "PUT", body });
      setApiKey("");
      await load();
      setMsg({ ok: true, text: "Saved." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ ok: boolean; dimensions?: number; model?: string; error?: string }>("/platform/embedding/test", { method: "POST" });
      setMsg(r.ok ? { ok: true, text: `Working: ${r.model} returns ${r.dimensions}-dimension vectors.` } : { ok: false, text: r.error ?? "Test failed." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function reindex() {
    setMsg(null);
    try {
      await api("/platform/embedding/reindex", { method: "POST" });
      await load();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    }
  }

  if (!state) return <><PageHead title="Embedding and Qdrant" narrow />{msg && <div className="page-body narrow"><div className="error" role="alert">{msg.text}</div></div>}</>;
  const r = state.reindex;

  return (
    <>
      <PageHead title="Embedding and Qdrant" narrow>
        {state.reindex_needed ? <span className="pill warn">Reindex needed</span> : <span className="pill ok">Index up to date</span>}
      </PageHead>
      <div className="page-body narrow">
        <p className="muted" style={{ margin: 0 }}>
          Every document chunk is turned into a vector by the embedding model and stored in Qdrant, one collection per customer.
          Any OpenAI-compatible embeddings endpoint works: the local TEI container (default), Ollama, vLLM or a cloud provider.
        </p>

        {state.reindex_needed && (
          <div className="notice" style={{ borderColor: "var(--warn)" }}>
            The model changed from <strong>{state.indexed_model}</strong> to <strong>{state.model}</strong>. Vectors from different models cannot be mixed:
            uploads fail until you reindex.
          </div>
        )}

        <form className="card" onSubmit={save}>
          <div className="card-head"><h2>Embedding service</h2></div>
          <div className="card-body stack">
            <label className="field">Endpoint URL (OpenAI-compatible, up to /v1)
              <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://embeddings/v1" />
            </label>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: 1, minWidth: 220 }}>Model
                <input className="input" value={model} onChange={(e) => setModel(e.target.value)} placeholder="BAAI/bge-m3" />
              </label>
              <label className="field" style={{ flex: 1, minWidth: 220 }}>API key (optional)
                <input className="input" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="new-password"
                  placeholder={state.api_key_set ? "Stored — leave empty to keep" : "Not needed for the local service"} />
              </label>
            </div>
            <div className="row">
              <button className="btn btn-primary" disabled={busy}>Save</button>
              <button type="button" className="btn" onClick={test} disabled={busy}>Test connection</button>
            </div>
            {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
          </div>
        </form>

        <section className="card">
          <div className="card-head"><h2 style={{ flex: 1 }}>Vector index</h2>
            <button className="btn btn-sm" onClick={reindex} disabled={running}><Icon name="refresh" />Reindex everything</button>
          </div>
          <div className="card-body stack" style={{ gap: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
              <div><div className="muted small">Indexed with</div>{state.indexed_model ?? "—"}{state.indexed_dim ? ` (${state.indexed_dim} dims)` : ""}</div>
              <div><div className="muted small">Collections</div>{state.index ? state.index.collections : "Qdrant not reachable"}</div>
              <div><div className="muted small">Vectors</div>{state.index ? state.index.points : "—"}</div>
            </div>
            {r && (
              <div className="small">
                Last reindex: <strong>{r.status}</strong>
                {r.total != null && ` · ${r.done ?? 0} of ${r.total} versions`}
                {r.finished_at && ` · finished ${new Date(r.finished_at).toLocaleString()}`}
                {r.error && <div className="error">{r.error}</div>}
              </div>
            )}
            <span className="muted small">Reindexing rebuilds every collection from the stored text; documents are not read again. Answers may miss documents until it finishes.</span>
          </div>
        </section>
      </div>
    </>
  );
}
