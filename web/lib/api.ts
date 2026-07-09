// Typed client for the Stock Advisor FastAPI backend.
// The bearer token is kept in localStorage (this is a client-rendered app).

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "sa_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string): void {
  window.localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  is_owner: boolean;
}
export interface Post {
  id: number;
  user_id: number;
  ticker: string | null;
  body: string;
  created_at: string;
  avatar: string;
  display_name: string;
  likes: number;
  liked: boolean;
  is_own: boolean;
}
export interface LeaderRow {
  rank: number;
  user_id: number;
  display_name: string;
  avatar: string;
  bio: string;
  avg_return: number;
  n_picks: number;
  following: boolean;
}
export interface AuthResult {
  token: string;
  user: User;
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((opts.headers as Record<string, string>) || {}),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}

export const api = {
  signup: (b: { username: string; password: string; display_name?: string }) =>
    req<AuthResult>("/api/auth/signup", { method: "POST", body: JSON.stringify(b) }),
  login: (b: { username: string; password: string }) =>
    req<AuthResult>("/api/auth/login", { method: "POST", body: JSON.stringify(b) }),
  me: () => req<User>("/api/me"),
  leaderboard: () => req<LeaderRow[]>("/api/community/leaderboard"),
  feed: () => req<Post[]>("/api/community/feed"),
  recent: () => req<Post[]>("/api/community/posts"),
  createPost: (b: { body: string; ticker?: string | null }) =>
    req<{ ok: boolean }>("/api/community/posts", { method: "POST", body: JSON.stringify(b) }),
  like: (id: number) => req<{ ok: boolean }>(`/api/community/posts/${id}/like`, { method: "POST" }),
  unlike: (id: number) => req<{ ok: boolean }>(`/api/community/posts/${id}/like`, { method: "DELETE" }),
  follow: (id: number) => req<{ ok: boolean }>(`/api/community/follow/${id}`, { method: "POST" }),
  unfollow: (id: number) => req<{ ok: boolean }>(`/api/community/follow/${id}`, { method: "DELETE" }),
};
