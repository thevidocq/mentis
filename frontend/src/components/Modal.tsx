import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useRef } from "react";
import { Icon } from "./Icon";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  danger?: boolean;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ title, onClose, children, footer, danger }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Keyboard users: focus moves into the dialog (unless a field already took it with autoFocus)
  // and goes back to the control that opened it when the dialog closes.
  // Read at the first render, before autoFocus inside the dialog moves the focus.
  const opener = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => {
    const el = box.current;
    if (el && !el.contains(document.activeElement)) {
      // A field of the body first; else the Close button (never a destructive button by default).
      (el.querySelector(".modal-body")?.querySelector<HTMLElement>(FOCUSABLE) ?? el.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    }
    const back = opener.current;
    return () => { if (back && document.contains(back)) back.focus(); };
  }, []);

  // Tab stays inside the dialog.
  function trap(e: ReactKeyboardEvent) {
    if (e.key !== "Tab" || !box.current) return;
    const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={box} onKeyDown={trap}>
        <div className="modal-head">
          {danger && <span style={{ color: "var(--danger)", display: "flex" }}><Icon name="alert" size={20} /></span>}
          <h2>{title}</h2>
          <button className="icon-btn" style={{ border: 0 }} aria-label="Close" onClick={onClose}><Icon name="x" /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}
