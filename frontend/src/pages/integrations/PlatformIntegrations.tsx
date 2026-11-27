import { useEffect, useState } from "react";
import { errorText } from "../../api/client";
import type { IntegrationPlugin } from "../../api/types";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";
import { integrationsApi, TYPE_LABEL } from "./integrationsApi";
import "./integrations.css";

/** Super-admin: which installed integration plugins tenant admins may use. */
export function PlatformIntegrations() {
  const [plugins, setPlugins] = useState<IntegrationPlugin[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [allowPrivate, setAllowPrivate] = useState<boolean | null>(null);

  useEffect(() => {
    integrationsApi.plugins().then(setPlugins).catch((e) => setMsg({ ok: false, text: errorText(e) }));
    integrationsApi.settings().then((s) => setAllowPrivate(s.allow_private)).catch(() => setAllowPrivate(null));
  }, []);

  async function togglePrivate() {
    if (allowPrivate === null || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      setAllowPrivate((await integrationsApi.setAllowPrivate(!allowPrivate)).allow_private);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function toggle(p: IntegrationPlugin) {
    if (!plugins || busy) return;
    setBusy(true);
    setMsg(null);
    const names = plugins.filter((x) => (x.name === p.name ? !x.enabled : x.enabled)).map((x) => x.name);
    try {
      setPlugins(await integrationsApi.setEnabled(names));
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Integrations" />
      <div className="page-body">
        <p className="muted" style={{ margin: 0 }}>
          Integration types installed with this release. Enable the ones tenant admins may configure for their customers;
          the credentials and addresses stay with each customer. Every integration is read only.
        </p>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
        {allowPrivate !== null && (
          <div className={`card integration-card${allowPrivate ? " notice-warn" : ""}`}>
            <div className="integration-main">
              <div className="integration-name">
                <strong>Private network addresses</strong>
                <span className="muted small">
                  Off: integrations reach only public HTTPS addresses. On: also private networks (10.x, 172.16–31.x, 192.168.x)
                  and plain HTTP, for on-premise systems reached through a VPN. Mentis' own services, loopback and cloud
                  metadata addresses stay refused either way.
                </span>
              </div>
              <span className="spacer" />
              <button type="button" role="switch" aria-checked={allowPrivate} className={`btn btn-sm${allowPrivate ? " btn-primary" : ""}`}
                disabled={busy} onClick={togglePrivate}>{allowPrivate ? "Allowed" : "Allow"}</button>
            </div>
          </div>
        )}
        {plugins && plugins.length === 0 && <div className="notice">No integration plugin is installed in this image.</div>}
        <div className="integration-list">
          {plugins?.map((p) => (
            <div key={p.name} className={`card integration-card${p.enabled ? "" : " off"}`}>
              <div className="integration-main">
                <span className="integration-icon"><Icon name="link" size={18} /></span>
                <div className="integration-name">
                  <strong>{p.label}</strong>
                  <span className="muted small">{TYPE_LABEL[p.type] ?? p.type} · {p.vendor} · v{p.version}</span>
                </div>
                <span className="spacer" />
                {p.instances ? <span className="muted small">{p.instances === 1 ? "1 customer integration" : `${p.instances} customer integrations`}</span> : null}
                <button type="button" role="switch" aria-checked={p.enabled} className={`btn btn-sm${p.enabled ? " btn-primary" : ""}`}
                  disabled={busy} onClick={() => toggle(p)}>{p.enabled ? "Enabled" : "Enable"}</button>
              </div>
              <div className="small muted">{p.description}</div>
              <div className="integration-ops small">
                {p.operations.map((o) => <span key={o.name} className="pill" title={o.description}>{o.label}</span>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
