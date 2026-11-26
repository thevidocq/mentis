import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import type { TenantRef } from "../api/types";
import { Icon } from "./Icon";

interface Row { kind: "item"; tenant: TenantRef }
interface Head { kind: "head"; label: string }

/**
 * Customer switcher for many customers: a button that opens a panel with a search box.
 * Order: General, the last customers used, then all the others alphabetically.
 */
export function CustomerSelect({ tenants, current, recent, onSelect }: {
  tenants: TenantRef[]; current: TenantRef | null; recent: string[]; onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const rows = useMemo<(Row | Head)[]>(() => {
    const needle = q.trim().toLowerCase();
    const byName = (a: TenantRef, b: TenantRef) => a.name.localeCompare(b.name);
    if (needle) {
      return tenants.filter((t) => t.name.toLowerCase().includes(needle)).sort(byName).map((tenant) => ({ kind: "item" as const, tenant }));
    }
    const general = tenants.filter((t) => t.is_general);
    const recentList = recent.map((id) => tenants.find((t) => t.id === id && !t.is_general)).filter((t): t is TenantRef => !!t).slice(0, 3);
    const rest = tenants.filter((t) => !t.is_general && !recentList.includes(t)).sort(byName);
    const out: (Row | Head)[] = general.map((tenant) => ({ kind: "item" as const, tenant }));
    if (recentList.length && rest.length > 3) {
      out.push({ kind: "head", label: "Recent" }, ...recentList.map((tenant) => ({ kind: "item" as const, tenant })));
      out.push({ kind: "head", label: "All customers" });
      out.push(...rest.map((tenant) => ({ kind: "item" as const, tenant })));
    } else {
      out.push(...tenants.filter((t) => !t.is_general).sort(byName).map((tenant) => ({ kind: "item" as const, tenant })));
    }
    return out;
  }, [tenants, recent, q]);
  const items = rows.filter((r): r is Row => r.kind === "item");

  function pick(t: TenantRef) {
    onSelect(t.id);
    setOpen(false);
    setQ("");
  }

  function key(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[active]) pick(items[active].tenant); }
    else if (e.key === "Escape") setOpen(false);
  }

  let index = -1;
  return (
    <div className="customer-select" ref={box}>
      <button type="button" className="input customer-select-btn" aria-haspopup="listbox" aria-expanded={open} aria-label="Customer"
        onClick={() => { setOpen(!open); setActive(0); }}>
        <span className="customer-select-name">{current?.name ?? "Choose a customer"}</span>
        <Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="customer-panel">
          <input className="input" type="search" autoFocus placeholder="Search customers…" aria-label="Search customers" value={q}
            onChange={(e) => { setQ(e.target.value); setActive(0); }} onKeyDown={key} />
          <ul role="listbox" aria-label="Customers">
            {rows.map((r, i) => {
              if (r.kind === "head") return <li key={`h${i}`} className="eyebrow customer-panel-head">{r.label}</li>;
              index += 1;
              const me = index;
              return (
                <li key={r.tenant.id} role="option" aria-selected={current?.id === r.tenant.id}
                  className={`${me === active ? "active" : ""}${current?.id === r.tenant.id ? " current" : ""}`}
                  onMouseEnter={() => setActive(me)} onMouseDown={(e) => { e.preventDefault(); pick(r.tenant); }}>
                  <span>{r.tenant.name}</span>
                  {r.tenant.is_general && <span className="muted small">shared</span>}
                  {current?.id === r.tenant.id && <Icon name="check" size={14} />}
                </li>
              );
            })}
            {items.length === 0 && <li className="muted small customer-panel-empty">No customer matches.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
