"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Holdings,
  type Snapshot,
  type Suggestion,
  type Decision,
  type Position,
  type SellSignal,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuth";
import Nav from "@/app/components/Nav";

const SELL_COLOR: Record<string, string> = {
  Sell: "#dc2626",
  Trim: "#b45309",
  Hold: "#15803d",
};

function usd(n: number): string {
  return "$" + Math.round(n).toLocaleString();
}
function posValue(p: Position): number {
  if (p.current_value != null) return p.current_value;
  const qty = p.quantity || 0;
  if (p.current_price != null) return p.current_price * qty;
  return (p.cost_basis || 0) * qty;
}

function EquityChart({ data }: { data: Snapshot[] }) {
  if (data.length < 2) {
    return (
      <div className="muted">
        Not enough history yet — a point is saved each day you open the Streamlit dashboard.
      </div>
    );
  }
  const w = 640;
  const h = 180;
  const pad = 10;
  const ys = data.map((d) => d.total_value);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const pts = data
    .map((d, i) => {
      const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((d.total_value - min) / span) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = ys[ys.length - 1] >= ys[0];
  const color = up ? "#15803d" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="Equity curve">
      <polyline fill="none" stroke={color} strokeWidth="2.5" points={pts} />
    </svg>
  );
}

export default function PortfolioPage() {
  const ready = useAuthGuard();
  const [holdings, setHoldings] = useState<Holdings | null>(null);
  const [snaps, setSnaps] = useState<Snapshot[]>([]);
  const [sugs, setSugs] = useState<Suggestion[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [sells, setSells] = useState<SellSignal[] | null>(null);
  const [loadingSells, setLoadingSells] = useState(false);

  async function loadSells() {
    setLoadingSells(true);
    try {
      setSells(await api.sellSignals());
    } finally {
      setLoadingSells(false);
    }
  }

  const load = useCallback(async () => {
    const [h, s, g, d] = await Promise.all([
      api.holdings(),
      api.snapshots(),
      api.suggestions(),
      api.decisions(),
    ]);
    setHoldings(h);
    setSnaps(s);
    setSugs(g);
    setDecisions(d);
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  if (!ready || !holdings) return <div className="wrap muted">Loading…</div>;

  const equity = holdings.positions.reduce((sum, p) => sum + posValue(p), 0);
  const total = equity + (holdings.cash || 0);

  return (
    <>
      <Nav />
      <div className="wrap">
        <h2>💼 My Portfolio</h2>
        <p className="muted">Private to you — only you ever see these dollar amounts.</p>

        <div className="row" style={{ gap: "0.85rem", flexWrap: "wrap", margin: "1rem 0" }}>
          <div className="card" style={{ flex: 1, minWidth: 160, marginBottom: 0 }}>
            <div className="muted">Portfolio Value</div>
            <div style={{ fontSize: "1.6rem", fontWeight: 800 }}>{usd(total)}</div>
          </div>
          <div className="card" style={{ flex: 1, minWidth: 160, marginBottom: 0 }}>
            <div className="muted">Positions</div>
            <div style={{ fontSize: "1.6rem", fontWeight: 800 }}>{holdings.positions.length}</div>
          </div>
          <div className="card" style={{ flex: 1, minWidth: 160, marginBottom: 0 }}>
            <div className="muted">Cash</div>
            <div style={{ fontSize: "1.6rem", fontWeight: 800 }}>{usd(holdings.cash || 0)}</div>
          </div>
        </div>

        <div className="card">
          <div className="section-title">📈 Portfolio value over time</div>
          <EquityChart data={snaps} />
        </div>

        <div className="card">
          <div className="section-title">🔻 When to Sell</div>
          <div className="muted" style={{ marginBottom: "0.6rem" }}>
            A sell-side review of your holdings — stop-losses, stretched valuations, fading
            momentum, and profit-taking on big winners.
          </div>
          {sells === null ? (
            <button className="primary" onClick={loadSells} disabled={loadingSells}>
              {loadingSells ? "Reviewing…" : "Check my holdings for sell signals"}
            </button>
          ) : sells.length === 0 ? (
            <div className="muted">No holdings to review yet.</div>
          ) : (
            sells.map((s) => (
              <div
                key={s.symbol}
                className="row"
                style={{ alignItems: "flex-start", padding: "0.55rem 0", borderTop: "1px solid #eef1f7" }}
              >
                <div style={{ minWidth: 96 }}>
                  <strong>{s.symbol}</strong>
                  <br />
                  <span className="muted">{s.quantity} sh</span>{" "}
                  {s.gl_pct != null && (
                    <span className={s.gl_pct >= 0 ? "pos" : "neg"}>
                      {s.gl_pct >= 0 ? "+" : ""}
                      {s.gl_pct}%
                    </span>
                  )}
                </div>
                <div style={{ minWidth: 118 }}>
                  <span
                    style={{
                      background: SELL_COLOR[s.verdict],
                      color: "#fff",
                      borderRadius: 999,
                      padding: "2px 12px",
                      fontWeight: 700,
                      fontSize: "0.8rem",
                    }}
                  >
                    {s.verdict}
                  </span>
                  <div className="muted" style={{ marginTop: "0.25rem" }}>
                    urgency {s.urgency}/100
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  {s.verdict !== "Hold" && s.suggested_sell_qty ? (
                    <div style={{ fontWeight: 700, fontSize: "0.85rem" }}>
                      Suggested: sell {s.suggested_sell_qty} share(s)
                    </div>
                  ) : null}
                  {s.reasons.slice(0, 3).map((r, i) => (
                    <div key={i} className="muted" style={{ fontSize: "0.82rem" }}>
                      • {r}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="card">
          <div className="section-title">Holdings</div>
          {holdings.positions.length === 0 ? (
            <div className="muted">
              No positions yet — import a CSV/PDF in the Streamlit app&apos;s Settings.
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "#94a3b8" }}>
                  <th>Ticker</th>
                  <th>Qty</th>
                  <th>Value</th>
                  <th>G/L</th>
                </tr>
              </thead>
              <tbody>
                {holdings.positions.map((p) => {
                  const gl = p.unrealized_gl;
                  return (
                    <tr key={p.symbol} style={{ borderTop: "1px solid #eef1f7" }}>
                      <td>
                        <strong>{p.symbol}</strong>
                      </td>
                      <td>{p.quantity ?? "—"}</td>
                      <td>{usd(posValue(p))}</td>
                      <td className={gl != null ? (gl >= 0 ? "pos" : "neg") : ""}>
                        {gl != null ? (gl >= 0 ? "+" : "") + usd(gl) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {sugs.length > 0 && (
          <div className="card">
            <div className="section-title">Latest AI suggestions</div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "#94a3b8" }}>
                  <th>Ticker</th>
                  <th>Verdict</th>
                  <th>Score</th>
                  <th>Upside</th>
                </tr>
              </thead>
              <tbody>
                {sugs.map((s) => (
                  <tr key={s.symbol} style={{ borderTop: "1px solid #eef1f7" }}>
                    <td>
                      <strong>{s.symbol}</strong>
                    </td>
                    <td>{s.action}</td>
                    <td>{Math.round(s.score)}</td>
                    <td className={s.upside_pct >= 0 ? "pos" : "neg"}>
                      {s.upside_pct >= 0 ? "+" : ""}
                      {s.upside_pct}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {decisions.length > 0 && (
          <div className="card">
            <div className="section-title">My decisions</div>
            {decisions.map((d) => (
              <div key={d.symbol} className="row" style={{ padding: "0.3rem 0" }}>
                <span>
                  {d.decision === "bought" ? "✅" : "🚫"} <strong>{d.symbol}</strong>{" "}
                  <span className="muted">
                    {d.decision} · {(d.decided_at || "").slice(0, 10)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
