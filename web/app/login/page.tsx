"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await api.login({ username, password })
          : await api.signup({ username, password, display_name: displayName });
      setToken(res.token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <div style={{ textAlign: "center", marginBottom: "1.5rem" }}>
        <div style={{ fontSize: "2rem" }}>📈</div>
        <h1 style={{ margin: "0.3rem 0", letterSpacing: "-0.03em" }}>Stock Advisor</h1>
        <p className="muted">Community — verified track records, not hot takes.</p>
      </div>
      <div className="card">
        <div className="tabbar">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
            Sign in
          </button>
          <button className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>
            Create account
          </button>
        </div>
        <form onSubmit={submit}>
          <label className="muted">Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          {mode === "signup" && (
            <>
              <label className="muted">Display name</label>
              <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </>
          )}
          <label className="muted">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
          <button className="primary" style={{ width: "100%", marginTop: "0.9rem" }} disabled={busy}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
          {error && <div className="error">{error}</div>}
        </form>
      </div>
    </div>
  );
}
