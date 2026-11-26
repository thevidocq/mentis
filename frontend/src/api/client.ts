// Thin fetch wrapper: JSON in/out, session cookie, CSRF header on every request.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, "");
  }
  return fallback;
}

// fetch() rejects only when the server cannot be reached (offline, VPS down, proxy error).
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "Mentis cannot be reached. Check your connection and try again.");
  }
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await send(path, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    headers: {
      "X-Mentis-Request": "1",
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (res.status === 401) sessionLost(path);
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, `Request failed (${res.status}).`));
  return data as T;
}

// The session expired or was revoked (password changed elsewhere, account disabled):
// tell the app, which goes back to the sign-in page. Sign-in steps report their own 401s.
const SIGN_IN_PATHS = ["/auth/login", "/auth/totp", "/auth/password", "/setup", "/invitations/accept"];
function sessionLost(path: string) {
  if (!SIGN_IN_PATHS.some((p) => path.startsWith(p))) window.dispatchEvent(new Event("mentis:session-lost"));
}

export async function apiUpload<T = unknown>(path: string, form: FormData): Promise<T> {
  const res = await send(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Mentis-Request": "1" },
    body: form,
  });
  const data = await res.json().catch(() => null);
  if (res.status === 401) sessionLost(path);
  if (res.status === 413) throw new ApiError(413, "The file is too large for the server.");
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, `Upload failed (${res.status}).`));
  return data as T;
}

export const errorText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");
