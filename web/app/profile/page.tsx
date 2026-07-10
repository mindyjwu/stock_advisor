"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Profile, type Member, type BlockedUser } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuth";
import Nav from "@/app/components/Nav";

export default function ProfilePage() {
  const ready = useAuthGuard();
  const [p, setP] = useState<Profile | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [blocked, setBlocked] = useState<BlockedUser[]>([]);
  const [bio, setBio] = useState("");
  const [avatar, setAvatar] = useState("🙂");
  const [pub, setPub] = useState(false);
  const [sr, setSr] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const prof = await api.profile();
    setP(prof);
    setBio(prof.bio || "");
    setAvatar(prof.avatar || "🙂");
    setPub(prof.is_public);
    setSr(prof.share_returns);
    setMembers(await api.members());
    setBlocked(await api.blocked());
  }, []);

  async function unblock(id: number) {
    await api.unblock(id);
    void load();
  }

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const prof = await api.updateProfile({ bio, avatar, is_public: pub, share_returns: sr });
    setP(prof);
    setMsg("Saved.");
  }

  async function toggleFollow(m: Member) {
    if (m.following) await api.unfollow(m.user_id);
    else await api.follow(m.user_id);
    void load();
  }

  if (!ready || !p) return <div className="wrap muted">Loading…</div>;

  return (
    <>
      <Nav />
      <div className="wrap" style={{ maxWidth: 760 }}>
        <div className="card row" style={{ gap: "1rem" }}>
          <span className="avatar-lg">{p.avatar}</span>
          <div>
            <h2 style={{ margin: 0 }}>{p.display_name}</h2>
            <span className="muted">
              @{p.username} · {p.followers} followers · {p.following} following
            </span>
          </div>
        </div>

        <form onSubmit={save} className="card">
          <div className="section-title">Edit profile</div>
          <label className="field-label">Bio</label>
          <textarea
            value={bio}
            maxLength={280}
            placeholder="A line about your investing style…"
            onChange={(e) => setBio(e.target.value)}
          />
          <label className="field-label">Avatar emoji</label>
          <input value={avatar} maxLength={8} style={{ maxWidth: 120 }} onChange={(e) => setAvatar(e.target.value)} />
          <label className="toggle-row">
            <input type="checkbox" checked={pub} onChange={(e) => setPub(e.target.checked)} />
            <span>Public profile — appear in the member list &amp; be followable</span>
          </label>
          <label className="toggle-row">
            <input type="checkbox" checked={sr} onChange={(e) => setSr(e.target.checked)} />
            <span>Share my track record — show my verified returns on the leaderboard</span>
          </label>
          <button className="primary" style={{ marginTop: "0.5rem" }}>
            Save profile
          </button>
          {msg && <div className="success">{msg}</div>}
        </form>

        <div className="section-title">Members</div>
        {members.length === 0 && <div className="muted">No public members yet.</div>}
        {members.map((m) => (
          <div key={m.user_id} className="card row">
            <span>
              {m.avatar} <strong>{m.display_name}</strong>
              <br />
              <span className="muted">{m.bio}</span>
            </span>
            <button className="right" onClick={() => toggleFollow(m)}>
              {m.following ? "Following" : "Follow"}
            </button>
          </div>
        ))}

        {blocked.length > 0 && (
          <>
            <div className="section-title">Blocked</div>
            {blocked.map((b) => (
              <div key={b.user_id} className="card row">
                <span>
                  {b.avatar} {b.display_name}
                </span>
                <button className="right" onClick={() => unblock(b.user_id)}>
                  Unblock
                </button>
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}
