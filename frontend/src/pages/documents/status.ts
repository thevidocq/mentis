import type { DocVersion } from "../../api/types";

/** One label + pill style for a version, combining processing status and approval. */
export function versionState(v: DocVersion): { label: string; pill: string } {
  if (v.status === "queued") return { label: "Queued", pill: "" };
  if (v.status === "processing") return { label: "Processing", pill: "warn" };
  if (v.status === "failed") return { label: "Failed", pill: "danger" };
  if (v.approval === "pending") return { label: "Waiting approval", pill: "warn" };
  if (v.approval === "rejected") return { label: "Rejected", pill: "danger" };
  if (v.is_active) return { label: "Active", pill: "ok" };
  return { label: "Archived", pill: "" };
}

export const isBusy = (v: DocVersion) => v.status === "queued" || v.status === "processing";

export function sizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const dateText = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

const UNIT: Record<string, [string, string]> = { pdf: ["page", "pages"], docx: ["section", "sections"], pptx: ["slide", "slides"], xlsx: ["sheet", "sheets"], md: ["section", "sections"], json: ["section", "sections"],
  csv: ["table", "tables"], tsv: ["table", "tables"], yaml: ["document", "documents"], png: ["image", "images"], jpg: ["image", "images"] };

export function unitText(fileType: string, n: number): string {
  const [one, many] = UNIT[fileType] ?? ["page", "pages"];
  return `${n} ${n === 1 ? one : many}`;
}
