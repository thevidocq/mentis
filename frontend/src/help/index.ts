// Help topics, loaded from the Markdown files in this folder (one folder per audience).
// The same files are the manuals in the repository (see docs/MANUALS.md).

import type { Role } from "../api/types";

const files = import.meta.glob("./*/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export interface Topic {
  id: string; // e.g. "super-admin/02-tenants"
  title: string;
  body: string;
}

export interface Group {
  id: string;
  label: string;
  topics: Topic[];
}

const LABELS: Record<string, string> = {
  "super-admin": "Super-admin",
  "tenant-admin": "Tenant admin",
  analyst: "Analyst",
  everyone: "Everyone",
};

function topicsOf(folder: string): Topic[] {
  return Object.entries(files)
    .filter(([path]) => path.startsWith(`./${folder}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, body]) => ({
      id: path.slice(2, -3),
      title: /^#\s+(.*)$/m.exec(body)?.[1] ?? path,
      body,
    }));
}

// Each profile sees its own guide plus the common topics. Super-admins also see the
// other guides, so they can support their users.
const AUDIENCES: Record<Role, string[]> = {
  analyst: ["analyst", "everyone"],
  tenant_admin: ["tenant-admin", "everyone"],
  super_admin: ["super-admin", "everyone", "tenant-admin", "analyst"],
};

export function helpFor(role: Role): Group[] {
  return AUDIENCES[role].map((folder) => ({ id: folder, label: LABELS[folder], topics: topicsOf(folder) }));
}
