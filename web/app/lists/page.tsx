"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type SharedList } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuth";
import Nav from "@/app/components/Nav";

export default function ListsPage() {
  const ready = useAuthGuard();
  const [lists, setLists] = useState<SharedList[]>([]);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setLists(await api.sharedLists());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load lists");
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  async function publish(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api.publishList(name);
      setName("");
      setMsg("Published your watchlist.");
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not publish");
    }
  }

  async function clone(id: number) {
    const r = await api.cloneList(id);
    setMsg(`Added ${r.added} new ticker(s) to your watchlist.`);
  }

  async function del(id: number) {
    await api.deleteList(id);
    void load();
  }

  if (!ready) return <div className="wrap muted">Loading…</div>;

  return (
    <>
      <Nav />
      <div className="wrap" style={{ maxWidth: 760 }}>
        <h2>📋 Shared Lists</h2>
        <form onSubmit={publish} className="card">
          <div className="field-label">
            Publish your current watchlist — symbols &amp; industries only, no holdings or dollar amounts.
          </div>
          <div className="row">
            <input
              placeholder="List name e.g. My AI & Semis picks"
              value={name}
              maxLength={60}
              onChange={(e) => setName(e.target.value)}
            />
            <button className="primary" disabled={!name.trim()}>
              Publish
            </button>
          </div>
          {msg && <div className="success">{msg}</div>}
          {error && <div className="error">{error}</div>}
        </form>

        <div className="section-title">Browse shared lists</div>
        {lists.length === 0 && <div className="muted">No shared lists yet — publish yours above.</div>}
        {lists.map((l) => (
          <div key={l.id} className="card">
            <div className="row">
              <strong>{l.name}</strong>
              <span className="right muted">
                {l.avatar} {l.display_name} · {l.tickers.length} tickers
              </span>
            </div>
            <div style={{ margin: "0.4rem 0" }}>
              {l.tickers.slice(0, 16).map((t) => (
                <span key={t.symbol} className="code-chip">
                  {t.symbol}
                </span>
              ))}
            </div>
            <div className="row">
              <button onClick={() => clone(l.id)}>➕ Clone to my watchlist</button>
              {l.is_own && <button onClick={() => del(l.id)}>🗑 Delete</button>}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
