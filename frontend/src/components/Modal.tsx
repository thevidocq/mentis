import { ReactNode, useEffect } from "react";
import { Icon } from "./Icon";

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  danger?: boolean;
}

export function Modal({ title, onClose, children, footer, danger }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
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
