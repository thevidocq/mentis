import type { AnswerCheck, CheckIssue } from "../../api/types";
import { Icon } from "../../components/Icon";

/** "Level 1", "Level 2" or "Level 1 + 2": which check found the problem (to report it). */
const levelText = (lv: number[]) => (lv.length > 1 ? "Level 1 + 2" : `Level ${lv[0]}`);

function message(i: CheckIssue): string {
  if (i.kind === "no_citations") return "Unverified answer: it cites no source. Check the documents before acting.";
  if (i.kind === "statement") return "1 statement is not supported by the sources.";
  if (i.kind === "uncited") return "1 statement cites no source, so it was not checked.";
  return `“${i.text}” is not in the sources${i.expected ? ` (the source says ${i.expected})` : ""}.`;
}

/** The checker's reason as a sentence: "not in the passage" -> "Not in the passage." */
const reasonText = (r: string) => { const t = r.trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") : ""; };

/** Texts to highlight in the answer. */
export const checkMarks = (c?: AnswerCheck | null) => (c && !c.hidden ? c.issues.map((i) => i.text).filter(Boolean) : []);

/** The quiet lines under an answer: what the answer check found, by which level. */
export function CheckNotes({ check, onOpenSource }: { check?: AnswerCheck | null; onOpenSource?: () => void }) {
  if (!check) return null;
  if (check.hidden) {
    return (
      <div className="check-notes">
        <div className="check-line muted"><span className="check-level">Level {check.issues.some((i) => i.level.includes(2)) ? "2" : "1"}</span>Answer hidden by the answer check.</div>
      </div>
    );
  }
  const open = onOpenSource && <button type="button" className="check-open" onClick={onOpenSource}>Open source ›</button>;
  return (
    <div className="check-notes" aria-live="polite">
      {check.issues.map((i, k) => (
        <div key={k} className="check-line warn">
          <Icon name="alert" size={13} />
          <span className="check-level">{levelText(i.level)}</span>
          <span>{message(i)}{i.reason ? <span className="check-reason"> {reasonText(i.reason)}</span> : null}</span>
          {i.kind !== "no_citations" && open}
        </div>
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
