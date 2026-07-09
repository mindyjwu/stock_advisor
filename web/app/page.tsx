"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  getToken,
  clearToken,
  type User,
  type Post,
  type LeaderRow,
} from "@/lib/api";
import Nav from "@/app/components/Nav";

function timeAgo(iso: string): string {
  return (iso || "").slice(0, 16).replace("T", " ") + " UTC";
}

function PostCard({ post, onChange }: { post: Post; onChange: () => void }) {
  async function toggleLike() {
    if (post.liked) await api.unlike(post.id);
    else await api.like(post.id);
    onChange();
  }
  return (
    <div className="card">
      <div className="row">
        <strong>
          {post.avatar} {post.display_name}
        </strong>
        {post.ticker && <span className="chip">${post.ticker}</span>}
        <span className="right muted">{timeAgo(post.created_at)}</span>
      </div>
      <div style={{ margin: "0.4rem 0 0.6rem", whiteSpace: "pre-wrap" }}>{post.body}</div>
      <button onClick={toggleLike}>
        {post.liked ? "❤" : "🤍"} {post.likes}
      </button>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [feed, setFeed] = useState<Post[]>([]);
  const [recent, setRecent] = useState<Post[]>([]);
  const [board, setBoard] = useState<LeaderRow[]>([]);
  const [tab, setTab] = useState<"following" | "everyone">("everyone");
  const [body, setBody] = useState("");
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [u, f, r, b] = await Promise.all([
        api.me(),
        api.feed(),
        api.recent(),
        api.leaderboard(),
      ]);
      setMe(u);
      setFeed(f);
      setRecent(r);
      setBoard(b);
    } catch {
      clearToken();
      router.push("/login");
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    void load();
  }, [load, router]);

  async function submitPost(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createPost({ body, ticker: ticker.trim() || null });
      setBody("");
      setTicker("");
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post");
    }
  }

  if (!me) return <div className="wrap muted">Loading…</div>;

  const posts = tab === "following" ? feed : recent;

  return (
    <>
      <Nav />

      <div className="wrap">
        <div className="banner">
          ⚠️ <strong>Not investment advice.</strong> Posts are opinions from other members;
          leaderboard returns come from users&apos; own logged picks and are not audited.
        </div>

        <div className="grid">
          <div>
            <form onSubmit={submitPost} className="card">
              <textarea
                placeholder="What are you watching today?"
                value={body}
                maxLength={500}
                onChange={(e) => setBody(e.target.value)}
              />
              <div className="row" style={{ marginTop: "0.6rem" }}>
                <input
                  style={{ maxWidth: 180 }}
                  placeholder="Ticker (optional)"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                />
                <button className="primary right" disabled={!body.trim()}>
                  Post
                </button>
              </div>
              {error && <div className="error">{error}</div>}
            </form>

            <div className="tabbar">
              <button className={tab === "everyone" ? "active" : ""} onClick={() => setTab("everyone")}>
                Everyone
              </button>
              <button className={tab === "following" ? "active" : ""} onClick={() => setTab("following")}>
                Following
              </button>
            </div>

            {posts.length === 0 && <div className="muted">No posts yet.</div>}
            {posts.map((p) => (
              <PostCard key={p.id} post={p} onChange={load} />
            ))}
          </div>

          <div>
            <div className="card">
              <div className="section-title">🏆 Leaderboard</div>
              <div className="muted" style={{ marginBottom: "0.6rem" }}>
                Avg return across each member&apos;s logged buy calls.
              </div>
              {board.length === 0 && <div className="muted">No verified track records yet.</div>}
              {board.map((u) => (
                <div key={u.user_id} className="row" style={{ padding: "0.4rem 0" }}>
                  <span className="rank">#{u.rank}</span>
                  <span>
                    {u.avatar} <strong>{u.display_name}</strong>
                    <br />
                    <span className="muted">{u.n_picks} pick(s)</span>
                  </span>
                  <span className={`right ${u.avg_return >= 0 ? "pos" : "neg"}`}>
                    {u.avg_return >= 0 ? "+" : ""}
                    {u.avg_return.toFixed(1)}%
                  </span>
                  <FollowButton row={u} onChange={load} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function FollowButton({ row, onChange }: { row: LeaderRow; onChange: () => void }) {
  async function toggle() {
    if (row.following) await api.unfollow(row.user_id);
    else await api.follow(row.user_id);
    onChange();
  }
  return (
    <button onClick={toggle} style={{ marginLeft: "0.4rem" }}>
      {row.following ? "Following" : "Follow"}
    </button>
  );
}
