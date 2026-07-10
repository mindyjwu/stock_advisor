"use client";

import { useCallback, useState } from "react";
import { api, type Post } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuth";
import Nav from "@/app/components/Nav";
import PostCard from "@/app/components/PostCard";

export default function DiscussPage() {
  const ready = useAuthGuard();
  const [ticker, setTicker] = useState("");
  const [active, setActive] = useState("");
  const [posts, setPosts] = useState<Post[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (t: string) => {
    if (!t) {
      setPosts([]);
      return;
    }
    try {
      setPosts(await api.thread(t));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load thread");
    }
  }, []);

  function open(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    setActive(t);
    setTicker(t);
    void load(t);
  }

  async function post(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createPost({ body, ticker: active });
      setBody("");
      void load(active);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post");
    }
  }

  if (!ready) return <div className="wrap muted">Loading…</div>;

  return (
    <>
      <Nav />
      <div className="wrap" style={{ maxWidth: 720 }}>
        <h2>💬 Discuss</h2>
        <p className="muted">Open a ticker&apos;s thread to read and join the conversation.</p>
        <form onSubmit={open} className="row" style={{ margin: "1rem 0" }}>
          <input placeholder="Ticker e.g. NVDA" value={ticker} onChange={(e) => setTicker(e.target.value)} />
          <button className="primary">Open thread</button>
        </form>

        {active && (
          <>
            <form onSubmit={post} className="card">
              <textarea
                placeholder={`Your take on $${active}…`}
                value={body}
                maxLength={500}
                onChange={(e) => setBody(e.target.value)}
              />
              <button className="primary right" style={{ marginTop: "0.6rem" }} disabled={!body.trim()}>
                Post to ${active}
              </button>
              {error && <div className="error">{error}</div>}
            </form>

            <div className="section-title">${active} discussion</div>
            {posts.length === 0 && <div className="muted">No posts yet — start the conversation above.</div>}
            {posts.map((p) => (
              <PostCard key={p.id} post={p} onChange={() => load(active)} />
            ))}
          </>
        )}
      </div>
    </>
  );
}
