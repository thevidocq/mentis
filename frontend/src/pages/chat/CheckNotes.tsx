import { useState } from "react";
import type { AnswerCheck, CheckIssue } from "../../api/types";
import type { Mark } from "../../components/Markdown";
import { Icon } from "../../components/Icon";

/** "Level 1", "Level 2" or "Level 1 + 2": which check found the problem (to report it). */
const levelText = (lv: number[]) => (lv.length > 1 ? "Level 1 + 2" : `Level ${lv[0]}`);

/** A finding contradicts or is missing from the sources; a note (uncited) only means "not verified". */
const isNote = (i: CheckIssue) => i.kind === "uncited";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One line for all the issues: "1 value not in the sources · 2 statements without a citation". */
function summary(issues: CheckIssue[]): string {
  const values = issues.filter((i) => i.kind === "value").length;
  const statements = issues.filter((i) => i.kind === "statement").length;
  const uncited = issues.filter(isNote).length;
  return [
    values && plural(values, "value not in the sources", "values not in the sources"),
    statements && plural(statements, "statement not supported by the sources", "statements not supported by the sources"),
    uncited && plural(uncited, "statement without a citation", "statements without a citation"),
  ].filter(Boolean).join(" · ");
}

function detail(i: CheckIssue): string {
  if (i.kind === "value") return `Not in the sources${i.expected ? `: the source says ${i.expected}` : ""}.`;
  if (i.kind === "statement") return "Not supported by the passages it cites.";
  return "No citation, so it was not verified.";
}

/** The checker's reason as a sentence: "not in the passage" -> "Not in the passage." */
const reasonText = (r: string) => { const t = r.trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") : ""; };

const quote = (t: string) => (t.length > 90 ? `${t.slice(0, 88).trimEnd()}…` : t);

/** Texts to highlight in the answer: findings in amber, uncited statements with a light dotted line. */
export const checkMarks = (c?: AnswerCheck | null): Mark[] =>
  c && !c.hidden ? c.issues.filter((i) => i.text).map((i) => ({ text: i.text, soft: isNote(i) })) : [];

/** The quiet line under an answer: what the answer check found, details on demand. */
export function CheckNotes({ check }: { check?: AnswerCheck | null }) {
  const [open, setOpen] = useState(false);
  if (!check) return null;
  if (check.hidden) {
    return (
      <div className="check-notes">
        <div className="check-line muted"><span className="check-level">Level {check.issues.some((i) => i.level.includes(2)) ? "2" : "1"}</span>Answer hidden by the answer check.</div>
      </div>
    );
  }
  const noCitations = check.issues.some((i) => i.kind === "no_citations");
  const issues = check.issues.filter((i) => i.kind !== "no_citations");
  const findings = issues.some((i) => !isNote(i));
  return (
    <div className="check-notes" aria-live="polite">
      {noCitations && (
        <div className="check-line warn"><Icon name="alert" size={13} /><span>Unverified answer: it cites no source. Check the documents before acting.</span></div>
      )}
      {issues.length > 0 && (
        <div className={`check-line ${findings ? "warn" : "muted"}`}>
          <Icon name={findings ? "alert" : "info"} size={13} />
          <span>{summary(issues)}</span>
          <button type="button" className="check-open" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide details" : "Details ›"}</button>
        </div>
      )}
      {open && issues.length > 0 && (
        <ul className="check-details">
          {issues.map((i, k) => (
            <li key={k} className={isNote(i) ? "note" : "finding"}>
              <span className="check-level">{levelText(i.level)}</span>
              <span>“{quote(i.text)}” — {detail(i)}{i.reason ? <span className="check-reason"> {reasonText(i.reason)}</span> : null}</span>
            </li>
          ))}
        </ul>
      )}
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
