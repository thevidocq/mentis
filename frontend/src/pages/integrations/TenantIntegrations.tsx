import { useCallback, useEffect, useState } from "react";
import { errorText } from "../../api/client";
import type { Integration } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";
import { IntegrationDialog } from "./IntegrationDialog";
import { integrationsApi, TYPE_LABEL, type TenantIntegrations as Data } from "./integrationsApi";
import { TryLookup } from "./TryLookup";
import "./integrations.css";

/** Tenant admin: the customer's integrations (ticketing, EDR), read-only, used in the chat with #. */
export function TenantIntegrations() {
  const { current } = useCurrentTenant();
  const tenantId = current?.id;
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ editing: Integration | null } | null>(null);
  const [trying, setTrying] = useState<Integration | null>(null);
  const [deleting, setDeleting] = useState<Integration | null>(null);
  const [tests, setTests] = useState<Record<string, { ok: boolean; detail: string } | "running">>({});

  const load = useCallback(() => {
    if (!tenantId) return;
    integrationsApi.list(tenantId).then(setData).catch((e) => setError(errorText(e)));
  }, [tenantId]);
  useEffect(load, [load]);

  if (!tenantId) return null;
  const pluginOf = (i: Integration) => data?.plugins.find((p) => p.name === i.plugin);

  async function test(i: Integration) {
    if (!tenantId || tests[i.id] === "running") return;
    setTests((t) => ({ ...t, [i.id]: "running" }));
    try {
      const r = await integrationsApi.test(tenantId, i.id);
      setTests((t) => ({ ...t, [i.id]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [i.id]: { ok: false, detail: errorText(e) } }));
    }
  }

  async function setEnabled(i: Integration, enabled: boolean) {
    if (!tenantId) return;
    setError(null);
    try {
      const saved = await integrationsApi.update(tenantId, i.id, { enabled });
      setData((d) => d && { ...d, integrations: d.integrations.map((x) => (x.id === saved.id ? saved : x)) });
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function remove(i: Integration) {
    if (!tenantId) return;
    try {
      await integrationsApi.remove(tenantId, i.id);
      setDeleting(null);
      setData((d) => d && { ...d, integrations: d.integrations.filter((x) => x.id !== i.id) });
    } catch (e) {
      setError(errorText(e));
      setDeleting(null);
    }
  }

  const canAdd = !!data && !data.general && data.plugins.length > 0;
  return (
    <>
      <PageHead title="Integrations">
        {canAdd && <button className="btn btn-primary" onClick={() => setDialog({ editing: null })}><Icon name="plus" />Add integration</button>}
      </PageHead>
      <div className="page-body">
        <p className="muted" style={{ margin: 0 }}>
          The customer's ticketing and EDR tools. In a chat on this customer, analysts choose them with <strong>#</strong>:
          Mentis reads tickets, devices and alerts and answers with the link to each record. Read only: nothing is ever changed in these systems.
        </p>
        {error && <div className="error" role="alert">{error}</div>}
        {data?.general && <div className="notice">The General Knowledge Base holds general knowledge only: integrations belong to a customer.</div>}
        {data && !data.general && data.plugins.length === 0 && (
          <div className="notice">No integration type is enabled yet. A super-admin enables them in <strong>Integrations</strong> of the platform.</div>
        )}
        {data && !data.general && data.integrations.length === 0 && data.plugins.length > 0 && (
          <div className="notice">No integration yet. <strong>Add integration</strong> to connect the customer's ServiceNow, Jira or EDR.</div>
        )}
        <div className="integration-list">
          {data?.integrations.map((i) => {
            const t = tests[i.id];
            const plugin = pluginOf(i);
            return (
              <div key={i.id} className={`card integration-card${i.enabled && i.available ? "" : " off"}`}>
                <div className="integration-main">
                  <span className="integration-icon"><Icon name="link" size={18} /></span>
                  <div className="integration-name">
                    <strong>{i.name}</strong>
                    <span className="muted small">{i.product}{i.type ? ` · ${TYPE_LABEL[i.type] ?? i.type}` : ""}</span>
                  </div>
                  <span className="spacer" />
                  {!i.available ? <span className="pill warn" title="Ask a super-admin to enable this type">Type not enabled</span>
                    : i.enabled ? <span className="pill ok">In use</span> : <span className="pill">Off</span>}
                </div>
                {t && (
                  <div className={`integration-test small ${t === "running" ? "muted" : t.ok ? "ok" : "bad"}`} role="status">
                    <Icon name={t === "running" ? "clock" : t.ok ? "check" : "alert"} size={14} />
                    {t === "running" ? "Testing…" : t.detail}
                  </div>
                )}
                <div className="integration-actions">
                  <button className="btn btn-sm" disabled={!i.available || t === "running"} onClick={() => test(i)}><Icon name="pulse" size={14} />Test</button>
                  {plugin && i.available && <button className="btn btn-sm" onClick={() => setTrying(i)}><Icon name="search" size={14} />Try a lookup</button>}
                  <button className="btn btn-sm" disabled={!i.available} onClick={() => setEnabled(i, !i.enabled)}>{i.enabled ? "Turn off" : "Turn on"}</button>
                  <span className="spacer" />
                  {plugin && <button className="icon-btn" aria-label={`Edit ${i.name}`} onClick={() => setDialog({ editing: i })}><Icon name="pencil" /></button>}
                  <button className="icon-btn" aria-label={`Delete ${i.name}`} onClick={() => setDeleting(i)}><Icon name="trash" /></button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {dialog && data && (
        <IntegrationDialog tenantId={tenantId} plugins={data.plugins} editing={dialog.editing} onClose={() => setDialog(null)}
          onSaved={() => { setDialog(null); load(); }} />
      )}
      {trying && pluginOf(trying) && (
        <TryLookup tenantId={tenantId} integration={trying} plugin={pluginOf(trying)!} onClose={() => setTrying(null)} />
      )}
      {deleting && (
        <Modal title={`Delete ${deleting.name}?`} danger onClose={() => setDeleting(null)}
          footer={<>
            <button className="btn" onClick={() => setDeleting(null)}>Cancel</button>
            <button className="btn btn-danger" onClick={() => remove(deleting)}>Delete</button>
          </>}>
          <p style={{ margin: 0 }}>Its stored credentials are deleted. Chats that used it continue without it.</p>
        </Modal>
      )}
    </>
  );
}
