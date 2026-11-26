import type { IntegrationPlugin, SchemaProp } from "../../api/types";
import type { ConfigValues } from "./integrationsApi";

/** Values for a new integration: the schema defaults. */
export function defaults(plugin: IntegrationPlugin): ConfigValues {
  const out: ConfigValues = {};
  for (const [k, p] of Object.entries(plugin.config_schema?.properties ?? {})) {
    if (!p.secret && p.default !== undefined) out[k] = p.default;
  }
  return out;
}

const shown = (p: SchemaProp, values: ConfigValues) =>
  !p.showIf || Object.entries(p.showIf).every(([k, v]) => String(values[k] ?? "") === v);

/**
 * The configuration form generated from the plugin's JSON Schema. Secret fields are write-only:
 * empty means "keep the stored one"; they are sent only when typed.
 */
export function ConfigForm({ plugin, values, secrets, stored, onChange, onSecret }: {
  plugin: IntegrationPlugin;
  values: ConfigValues;
  secrets: Record<string, string>;
  stored?: Record<string, boolean>;  // secrets already saved (edit)
  onChange: (key: string, value: string | boolean | number) => void;
  onSecret: (key: string, value: string) => void;
}) {
  const props = plugin.config_schema?.properties ?? {};
  const required = new Set(plugin.config_schema?.required ?? []);
  return (
    <div className="stack" style={{ gap: 12 }}>
      {Object.entries(props).filter(([, p]) => shown(p, values)).map(([key, p]) => {
        const title = `${p.title ?? key}${required.has(key) && !(p.secret && stored?.[key]) ? " *" : ""}`;
        const hint = p.description ? <span className="muted small">{p.description}</span> : null;
        if (p.type === "boolean") {
          return (
            <label key={key} className="row" style={{ gap: 8 }}>
              <input type="checkbox" checked={!!values[key]} onChange={(e) => onChange(key, e.target.checked)} />{title}{hint}
            </label>
          );
        }
        if (p.enum) {
          return (
            <label key={key} className="field">{title}
              <select className="input" value={String(values[key] ?? p.default ?? "")} onChange={(e) => onChange(key, e.target.value)}>
                {p.enum.map((v, i) => <option key={v} value={v}>{p.enumLabels?.[i] ?? v}</option>)}
              </select>
              {hint}
            </label>
          );
        }
        if (p.secret) {
          return (
            <label key={key} className="field">{title}
              <input className="input" type="password" autoComplete="new-password" value={secrets[key] ?? ""} maxLength={p.maxLength}
                placeholder={stored?.[key] ? "Stored — leave empty to keep" : ""} onChange={(e) => onSecret(key, e.target.value)} />
              {hint}
            </label>
          );
        }
        return (
          <label key={key} className="field">{title}
            <input className="input" type={p.format === "uri" ? "url" : p.type === "integer" ? "number" : "text"} maxLength={p.maxLength}
              value={String(values[key] ?? "")} autoComplete="off"
              onChange={(e) => onChange(key, p.type === "integer" ? Number(e.target.value) : e.target.value)} />
            {hint}
          </label>
        );
      })}
    </div>
  );
}

/** What is sent: the visible plain values, and only the secrets that were typed. */
export function payload(plugin: IntegrationPlugin, values: ConfigValues, secrets: Record<string, string>): ConfigValues {
  const out: ConfigValues = {};
  for (const [k, p] of Object.entries(plugin.config_schema?.properties ?? {})) {
    if (p.secret) {
      if (secrets[k]) out[k] = secrets[k];
    } else if (values[k] !== undefined) {
      out[k] = values[k];
    }
  }
  return out;
}
