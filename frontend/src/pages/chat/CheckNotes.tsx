import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AnswerCheck, CheckIssue } from "../../api/types";
import { Icon } from "../../components/Icon";

/** "Level 1", "Level 2" or "Level 1 + 2": which check found the problem (to report it). */
const levelText = (lv: number[]) => (lv.length > 1 ? "Level 1 + 2" : `Level ${lv[0]}`);

/** The checker's reason as a sentence: "not in the passage" -> "Not in the passage." */
const reasonText = (r: string) => { const t = r.trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") : ""; };

function title(i: CheckIssue): string {
  if (i.kind === "value") return "Value not in the sources";
  if (i.kind === "statement") return "Not supported by the sources";
  return "No source cited";
}

function detail(i: CheckIssue): string {
  if (i.kind === "value") return `“${i.text}” is not in the passage it cites${i.expected ? `: the source says ${i.expected}` : ""}.`;
  if (i.kind === "statement") return i.reason ? reasonText(i.reason) : "The passage it cites does not support this statement.";
  return "This statement cites no passage, so it could not be checked.";
}

/** Issues shown in the text (a mark and a flag): everything but "no citations at all". */
export const markedIssues = (c?: AnswerCheck | null) => (c && !c.hidden ? c.issues.filter((i) => i.kind !== "no_citations" && i.text) : []);

/** Texts to underline in the answer, in the order of markedIssues. */
export const checkMarks = (c?: AnswerCheck | null) => markedIssues(c).map((i) => i.text);

/** The small ⚠ after a flagged statement (after its citations): hover or tap shows what the check found. */
export function CheckFlag({ issue, cites, onPassage }: { issue: CheckIssue; cites: number[]; onPassage?: (n: number) => void }) {
  const [open, setOpen] = useState(false);
  const pinned = useRef(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) { pinned.current = false; setOpen(false); }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <span className="check-flag" ref={box}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned.current) setOpen(false); }}>
      <button type="button" className="check-flag-btn" aria-label={`${levelText(issue.level)}: ${title(issue)}`} aria-expanded={open}
        onClick={() => { pinned.current = !pinned.current || !open; setOpen(pinned.current); }}>
        <Icon name="alert" size={12} />
      </button>
      {open && (
        <span className="check-pop" role="tooltip">
          <span className="check-pop-title">{levelText(issue.level)} · {title(issue)}</span>
          <span>{detail(issue)}</span>
          {cites.length > 0 && onPassage && (
            <button type="button" className="check-open" onClick={() => { setOpen(false); onPassage(cites[0]); }}>Open passage {cites[0]} ›</button>
          )}
        </span>
      )}
    </span>
  );
}

function Line({ level, children }: { level?: string; children: ReactNode }) {
  return (
    <div className="check-line warn">
      <Icon name="alert" size={13} />
      {level && <span className="check-level">{level}</span>}
      <span>{children}</span>
    </div>
  );
}

/** The quiet line under an answer. Each problem is marked in the text (⚠ after the statement); here
 * one summary line, plus a full line only for a problem that could not be placed in the text. */
export function CheckNotes({ check, placed }: { check?: AnswerCheck | null; placed?: boolean[] }) {
  if (!check) return null;
  if (check.hidden) {
    return (
      <div className="check-notes">
        <div className="check-line muted"><span className="check-level">Level {check.issues.some((i) => i.level.includes(2)) ? "2" : "1"}</span>Answer hidden by the answer check.</div>
      </div>
    );
  }
  const marked = markedIssues(check);
  const inText = marked.filter((_, k) => placed?.[k]).length;
  const loose = marked.filter((_, k) => !placed?.[k]);
  return (
    <div className="check-notes" aria-live="polite">
      {check.issues.some((i) => i.kind === "no_citations") && (
        <Line>Unverified answer: it cites no source. Check the documents before acting.</Line>
      )}
      {inText > 0 && (
        <Line>{inText === 1 ? "1 statement may not match the sources: check the marked one." : `${inText} statements may not match the sources: check the marked ones.`}</Line>
      )}
      {loose.map((i, k) => (
        <Line key={k} level={levelText(i.level)}>{title(i)}: “{i.text.length > 90 ? `${i.text.slice(0, 88)}…` : i.text}”. {detail(i)}</Line>
      ))}
      {check.issues.length === 0 && check.level2 === "ok" && (
        <div className="check-line ok"><Icon name="check" size={13} /><span>Matches the sources</span></div>
      )}
      {check.level2 === "pending" && (
        <div className="check-line muted"><span className="check-spin" aria-hidden="true" /><span>Checking against the sources…</span></div>
      )}
      {check.level2 === "unavailable" && (
        <div className="check-line muted"><Icon name="alert" size={13} /><span className="check-level">Level 2</span><span>Check not available: verify the sources before acting.</span></div>
      )}
    </div>
  );
}
