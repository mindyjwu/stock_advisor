"use client";

import { useState } from "react";
import { api, type Post } from "@/lib/api";

function when(iso: string): string {
  return (iso || "").slice(0, 16).replace("T", " ") + " UTC";
}

export default function PostCard({ post, onChange }: { post: Post; onChange: () => void }) {
  const [reported, setReported] = useState(false);

  async function toggleLike() {
    if (post.liked) await api.unlike(post.id);
    else await api.like(post.id);
    onChange();
  }
  async function del() {
    await api.deletePost(post.id);
    onChange();
  }
  async function report() {
    await api.report({ post_id: post.id, reason: "reported" });
    setReported(true);
  }
  async function block() {
    await api.block(post.user_id);
    onChange();
  }

  return (
    <div className="card">
      <div className="row">
        <strong>
          {post.avatar} {post.display_name}
        </strong>
        {post.ticker && <span className="chip">${post.ticker}</span>}
        <span className="right muted">{when(post.created_at)}</span>
      </div>
      <div style={{ margin: "0.4rem 0 0.6rem", whiteSpace: "pre-wrap" }}>{post.body}</div>
      <div className="row" style={{ gap: "0.4rem" }}>
        <button onClick={toggleLike}>
          {post.liked ? "❤" : "🤍"} {post.likes}
        </button>
        {post.is_own ? (
          <button onClick={del}>🗑 Delete</button>
        ) : (
          <>
            <button onClick={report} disabled={reported}>
              {reported ? "🚩 Reported" : "🚩 Report"}
            </button>
            <button onClick={block}>🚫 Block</button>
          </>
        )}
      </div>
    </div>
  );
}
