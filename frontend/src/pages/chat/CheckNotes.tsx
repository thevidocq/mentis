import type { ReactNode } from "react";
import type { AnswerCheck, CheckIssue } from "../../api/types";
import { Icon } from "../../components/Icon";

/** "Level 1", "Level 2" or "Level 1 + 2": which check found the problem (to report it). */
const levelText = (lv: number[]) => (lv.length > 1 ? "Level 1 + 2" : `Level ${lv[0]}`);

function message(i: CheckIssue): string {
  if (i.kind === "statement") return "1 statement is not supported by the sources.";
  return `“${i.text}” is not in the sources${i.expected ? ` (the source says ${i.expected})` : ""}.`;
}

/** The checker's reason as a sentence: "not in the passage" -> "Not in the passage." */
const reasonText = (r: string) => { const t = r.trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") : ""; };

/** Texts to highlight in the answer. */
export const checkMarks = (c?: AnswerCheck | null) => (c && !c.hidden ? c.issues.map((i) => i.text).filter(Boolean) : []);

function Line({ level, children }: { level?: string; children: ReactNode }) {
  return (
    <div className="check-line warn">
      <Icon name="alert" size={13} />
      {level && <span className="check-level">{level}</span>}
      <span>{children}</span>
    </div>
  );
}

/** The quiet lines under an answer: what the answer check found, by which level. Statements that
 * cite no source are one line, however many; each wrong value and each rejected statement its own. */
export function CheckNotes({ check }: { check?: AnswerCheck | null }) {
  if (!check) return null;
  if (check.hidden) {
    return (
      <div className="check-notes">
        <div className="check-line muted"><span className="check-level">Level {check.issues.some((i) => i.level.includes(2)) ? "2" : "1"}</span>Answer hidden by the answer check.</div>
      </div>
    );
  }
  const uncited = check.issues.filter((i) => i.kind === "uncited").length;
  const others = check.issues.filter((i) => i.kind === "value" || i.kind === "statement");
  return (
    <div className="check-notes" aria-live="polite">
      {check.issues.some((i) => i.kind === "no_citations") && (
        <Line>Unverified answer: it cites no source. Check the documents before acting.</Line>
      )}
      {others.map((i, k) => (
        <Line key={k} level={levelText(i.level)}>
          {message(i)}{i.reason ? <span className="check-reason"> {reasonText(i.reason)}</span> : null}
        </Line>
      ))}
      {uncited > 0 && (
        <Line level="Level 1">
          {uncited === 1 ? "1 statement cites no source, so it was not checked." : `${uncited} statements cite no source, so they were not checked.`}
        </Line>
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
