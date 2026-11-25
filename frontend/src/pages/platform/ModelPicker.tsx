import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmKind } from "../../api/types";
import { Icon } from "../../components/Icon";

interface ModelOption { id: string; label: string }

const OTHER = "__other__";

/** Model of an AI provider: picked from the list the provider returns, or typed when it has none. */
export function ModelPicker({ kind, baseUrl, apiKey, providerId, value, onChange }: {
  kind: LlmKind; baseUrl: string; apiKey: string; providerId?: string; value: string; onChange: (v: string) => void;
}) {
  const [models, setModels] = useState<ModelOption[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(false);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const list = await api<ModelOption[]>("/llm/models", {
        method: "POST", body: { kind, base_url: baseUrl.trim(), api_key: apiKey || undefined, provider_id: providerId },
      });
      setModels(list);
      setManual(list.length === 0 || (!!value && !list.some((m) => m.id === value)));
      if (!value && list.length) onChange(list[0].id);
    } catch (e) {
      setModels(null);
      setManual(true);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  // Editing a saved provider: its stored key lets us list the models right away.
  useEffect(() => {
    if (providerId && baseUrl) void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A different provider type or address means a different list.
  useEffect(() => { setModels(null); setError(null); }, [kind, baseUrl]);

  const canLoad = /^https?:\/\/.+/.test(baseUrl.trim());
  return (
    <div className="field">
      <span>Model</span>
      <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
        {models && !manual ? (
          <select className="input mono" aria-label="Model" style={{ flex: 1, minWidth: 0 }} value={value}
            onChange={(e) => (e.target.value === OTHER ? setManual(true) : onChange(e.target.value))}>
            {!value && <option value="">Choose a model…</option>}
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            <option value={OTHER}>Other (type the name)…</option>
          </select>
        ) : (
          <input className="input mono" aria-label="Model" style={{ flex: 1, minWidth: 0 }} value={value}
            placeholder={models ? "Model name" : "Load the list, or type the name"} onChange={(e) => onChange(e.target.value)} />
        )}
        <button type="button" className="btn" disabled={!canLoad || busy} onClick={load} title="Ask the provider which models it offers">
          <Icon name="refresh" />{busy ? "Loading…" : models ? "Reload" : "Load models"}
        </button>
      </div>
      {models && manual && models.length > 0 && (
        <button type="button" className="link-btn small" onClick={() => setManual(false)}>Choose from the {models.length} models of the provider</button>
      )}
      {error && <span className="error small">{error}</span>}
      {!models && !error && <span className="muted small">Fill in the URL (and the API key if needed), then load the models the provider offers.</span>}
    </div>
  );
}
