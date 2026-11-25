import { api } from "../../api/client";
import type { ChatFull, ChatMessage, ChatSummary, Exchange, ScopeOption } from "../../api/types";

export const chatApi = {
  scopes: () => api<ScopeOption[]>("/chats/scopes"),
  list: (q = "") => api<ChatSummary[]>(`/chats${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`),
  get: (id: string) => api<ChatFull>(`/chats/${id}`),
  create: (tenantId: string | null, message: string) => api<Exchange>("/chats", { method: "POST", body: { tenant_id: tenantId, message } }),
  ask: (id: string, message: string) => api<Exchange>(`/chats/${id}/messages`, { method: "POST", body: { message } }),
  rename: (id: string, title: string) => api<ChatSummary>(`/chats/${id}`, { method: "PATCH", body: { title } }),
  remove: (id: string) => api<void>(`/chats/${id}`, { method: "DELETE" }),
  feedback: (chatId: string, msgId: string, value: 1 | -1 | null) =>
    api<ChatMessage>(`/chats/${chatId}/messages/${msgId}/feedback`, { method: "POST", body: { value } }),
};

// Sidebar groups, like other chat tools.
export function groupByDay(chats: ChatSummary[]): { label: string; items: ChatSummary[] }[] {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const day = 86_400_000;
  const groups: Record<string, ChatSummary[]> = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
  for (const c of chats) {
    const t = new Date(c.updated_at).getTime();
    const key = t >= start.getTime() ? "Today" : t >= start.getTime() - day ? "Yesterday" : t >= start.getTime() - 7 * day ? "Previous 7 days" : "Older";
    groups[key].push(c);
  }
  return Object.entries(groups).filter(([, items]) => items.length).map(([label, items]) => ({ label, items }));
}
