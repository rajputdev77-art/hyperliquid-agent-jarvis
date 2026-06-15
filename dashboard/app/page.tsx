"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  Account,
  Combined,
  Decision,
  Market,
  Position,
  Trade,
  getApiUrl,
  setApiUrl,
  clearApiUrl,
  probeApi,
} from "@/lib/api";

type DecisionTagged = Decision & { market?: "crypto" | "stocks" };
type TradeTagged = Trade & { market?: "crypto" | "stocks" };
type PositionTagged = Position & { market: "crypto" | "stocks" };

/* ---------- formatting ---------- */
const fmtUsd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtUsdSign = (n: number | null | undefined) => {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  const abs = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${sign}$${abs}`;
};
const fmtPctSign = (n: number | null | undefined, decimals = 2) => {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(decimals)}%`;
};
const fmtSize = (n: number, market: "crypto" | "stocks") =>
  market === "stocks" ? n.toFixed(3) : Math.abs(n) >= 1 ? n.toFixed(4) : n.toFixed(6);
const fmtTime = (d: Date) =>
  d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

/* ---------- equity history ---------- */
type EquityPoint = { t: number; v: number };
const EQUITY_KEY = "jarvis.equity.v1";
const EQUITY_MAX_POINTS = 2000;

function loadEquity(): EquityPoint[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(EQUITY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}
function saveEquity(pts: EquityPoint[]) {
  try {
    window.localStorage.setItem(EQUITY_KEY, JSON.stringify(pts.slice(-EQUITY_MAX_POINTS)));
  } catch {}
}

type Range = "1H" | "1D" | "1W" | "ALL";
const RANGE_MS: Record<Range, number> = {
  "1H": 60 * 60 * 1000,
  "1D": 24 * 60 * 60 * 1000,
  "1W": 7 * 24 * 60 * 60 * 1000,
  ALL: Number.POSITIVE_INFINITY,
};

/* ---------- icons ---------- */
const Ic = ({ d, size = 14, sw = 1.75 }: { d: string; size?: number; sw?: number }) => (
  <svg
    className="ic"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={sw}
    strokeLinecap="round"
    strokeLinejoin="round"
    dangerouslySetInnerHTML={{ __html: d }}
  />
);
const ICON = {
  triUp: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  arrowUpRight: '<polyline points="7 17 17 7"/><polyline points="9 7 17 7 17 15"/>',
  arrowDownRight: '<polyline points="7 7 17 17"/><polyline points="17 9 17 17 9 17"/>',
  inbox: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/>',
};

const assetGlyph = (market: "crypto" | "stocks") => (market === "crypto" ? "₿" : "$");

/* ---------- main page ---------- */
export default function Home() {
  const [market, setMarket] = useState<Market>("combined");
  const [account, setAccount] = useState<Account | null>(null);
  const [combined, setCombined] = useState<Combined | null>(null);
  const [positions, setPositions] = useState<{ crypto: Position[]; stocks: Position[] } | null>(null);
  const [trades, setTrades] = useState<TradeTagged[]>([]);
  const [decisions, setDecisions] = useState<DecisionTagged[]>([]);
  const [stocksOk, setStocksOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [range, setRange] = useState<Range>("1D");
  const [tradeRange, setTradeRange] = useState<"1D" | "7D" | "30D" | "ALL">("7D");
  const [apiUrl, setApiUrlState] = useState<string>("");
  const [showFix, setShowFix] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    setEquity(loadEquity());
    setApiUrlState(getApiUrl());
  }, []);

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    const pull = async () => {
      try {
        const h = await api.health(ctrl.signal);
        if (!alive) return;
        setStocksOk(!!h.stocks_db);

        if (market === "combined") {
          const [c, p, t, d] = await Promise.all([
            api.account("combined", ctrl.signal) as Promise<Combined>,
            api.positionsBoth(ctrl.signal),
            api.historyBoth(50, ctrl.signal),
            api.decisionsBoth(20, ctrl.signal),
          ]);
          if (!alive) return;
          setCombined(c);
          setAccount(c.total);
          setPositions(p);
          setTrades(t.trades);
          setDecisions(d.decisions);
        } else {
          const [a, p, t, d] = await Promise.all([
            api.account(market, ctrl.signal) as Promise<Account>,
            api.positions(market, ctrl.signal),
            api.history(market, 50, ctrl.signal),
            api.decisions(market, 20, ctrl.signal),
          ]);
          if (!alive) return;
          setAccount(a);
          setCombined(null);
          setPositions(
            market === "crypto"
              ? { crypto: p.positions, stocks: [] }
              : { crypto: [], stocks: p.positions },
          );
          setTrades(t.trades.map((x) => ({ ...x, market } as TradeTagged)));
          setDecisions(d.decisions.map((x) => ({ ...x, market } as DecisionTagged)));
        }

        const now = new Date();
        setUpdated(now);
        setErr(null);
        setEquity((prev) => {
          const value =
            market === "combined"
              ? account?.total_value
              : account?.total_value;
          // We need the freshly fetched value, not the stale state. Pull from response above.
          return prev;
        });
      } catch (e: unknown) {
        if (!alive) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        setErr(e instanceof Error ? e.message : "fetch error");
      }
    };
    pull();
    const t = setInterval(pull, 10_000);
    return () => {
      alive = false;
      ctrl.abort();
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, retryNonce]);

  // Append equity samples whenever account.total_value changes.
  useEffect(() => {
    if (!account) return;
    const now = Date.now();
    setEquity((prev) => {
      const last = prev[prev.length - 1];
      if (last && Math.abs(last.v - account.total_value) < 1e-6 && now - last.t < 1000) return prev;
      const next = [...prev, { t: now, v: account.total_value }].slice(-EQUITY_MAX_POINTS);
      saveEquity(next);
      return next;
    });
  }, [account?.total_value]); // eslint-disable-line react-hooks/exhaustive-deps

  const onRetry = useCallback(() => setRetryNonce((n) => n + 1), []);
  const onSaveApiUrl = useCallback((next: string) => {
    setApiUrl(next);
    setApiUrlState(getApiUrl());
    setShowFix(false);
    setErr(null);
    setRetryNonce((n) => n + 1);
  }, []);
  const onResetApiUrl = useCallback(() => {
    clearApiUrl();
    setApiUrlState(getApiUrl());
    setShowFix(false);
    setErr(null);
    setRetryNonce((n) => n + 1);
  }, []);

  /* ---------- derived ---------- */
  const isStale = updated ? Date.now() - updated.getTime() > 30_000 : false;

  const totalPnlSinceInitial = account ? account.total_value - account.initial_balance : null;
  const pctSinceInitial =
    account && account.initial_balance > 0
      ? ((account.total_value - account.initial_balance) / account.initial_balance) * 100
      : null;

  const allPositions: PositionTagged[] = useMemo(() => {
    if (!positions) return [];
    return [
      ...positions.crypto.map((p) => ({ ...p, market: "crypto" as const })),
      ...positions.stocks.map((p) => ({ ...p, market: "stocks" as const })),
    ];
  }, [positions]);

  const visiblePositions =
    market === "combined" ? allPositions : allPositions.filter((p) => p.market === market);

  const openUnrealPnl = useMemo(
    () => visiblePositions.reduce((acc, p) => acc + (p.pnl ?? 0), 0),
    [visiblePositions]
  );

  const realized7d = useMemo(() => {
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    let sum = 0;
    let n = 0;
    let wins = 0;
    for (const t of trades) {
      const ts = t.closed_at ? Date.parse(t.closed_at) : 0;
      if (ts >= cutoff) {
        sum += t.realized_pnl ?? 0;
        n += 1;
        if ((t.realized_pnl ?? 0) > 0) wins += 1;
      }
    }
    const winPct = n > 0 ? Math.round((wins / n) * 100) : null;
    return { sum, n, winPct };
  }, [trades]);

  const exposure = useMemo(() => {
    if (!account || account.total_value <= 0) return null;
    let crypto = 0;
    let stocks = 0;
    for (const p of allPositions) {
      const mark = p.entryPx + (Math.abs(p.szi) > 0 ? p.pnl / p.szi : 0);
      const notional = Math.abs(p.szi) * mark;
      if (p.market === "crypto") crypto += notional;
      else stocks += notional;
    }
    const cryptoPct = (crypto / account.total_value) * 100;
    const stocksPct = (stocks / account.total_value) * 100;
    const totalPct = cryptoPct + stocksPct;
    const cashPct = Math.max(0, 100 - totalPct);
    return { cryptoPct, stocksPct, cashPct, totalPct };
  }, [allPositions, account]);

  const drawdown = useMemo(() => {
    if (equity.length < 2) return null;
    const peak = equity.reduce((m, p) => (p.v > m ? p.v : m), equity[0].v);
    const cur = equity[equity.length - 1].v;
    if (peak <= 0) return null;
    return ((cur - peak) / peak) * 100;
  }, [equity]);

  const todaysChange = useMemo(() => {
    if (equity.length < 2 || !account) return null;
    const startOfDay = new Date();
    startOfDay.setHours(0, 0, 0, 0);
    const todayStart = equity.find((p) => p.t >= startOfDay.getTime());
    if (!todayStart) return null;
    const delta = account.total_value - todayStart.v;
    const pct = todayStart.v > 0 ? (delta / todayStart.v) * 100 : 0;
    return { delta, pct };
  }, [equity, account]);

  const cycle = decisions[0]?.cycle ?? null;
  const positionsByMarket = {
    combined: allPositions.length,
    crypto: positions?.crypto.length ?? 0,
    stocks: positions?.stocks.length ?? 0,
  };

  const filteredTrades = useMemo(() => {
    const now = Date.now();
    const span =
      tradeRange === "1D" ? 24 * 60 * 60 * 1000
        : tradeRange === "7D" ? 7 * 24 * 60 * 60 * 1000
        : tradeRange === "30D" ? 30 * 24 * 60 * 60 * 1000
        : Number.POSITIVE_INFINITY;
    return trades.filter((t) => {
      if (!t.closed_at) return false;
      const ts = Date.parse(t.closed_at);
      return now - ts <= span;
    });
  }, [trades, tradeRange]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo">J</div>
          <div className="wordmark">jarvis</div>
        </div>
        <nav className="topnav">
          <a className="active">overview</a>
          <a>positions</a>
          <a>trades</a>
          <a>decisions</a>
          <a>risk</a>
        </nav>
        <div className="top-right">
          <span className="kbd">⌘ K</span>
          <span className={`live${isStale ? " stale" : ""}`}>
            <span className="dot"></span>
            {isStale ? "STALE" : "LIVE"} · {updated ? fmtTime(updated) : "—"}
          </span>
        </div>
      </header>

      <div className="paper-banner">
        <Ic d={ICON.triUp} size={14} />
        <span>
          <b>PAPER MODE</b>
          <span className="sep">·</span>no real capital at risk
          <span className="sep">·</span>simulated fills at live mid + 0.05% slippage
        </span>
      </div>

      {err && (
        <div className="err-banner">
          <span>
            can&apos;t reach api at <code className="code-inline">{apiUrl}</code> · {err}
          </span>
          <div className="err-actions">
            <button className="btn-ghost" onClick={onRetry}>retry</button>
            <button className="btn-primary" onClick={() => setShowFix(true)}>fix it</button>
          </div>
        </div>
      )}

      {showFix && (
        <FixApiDialog
          current={apiUrl}
          onClose={() => setShowFix(false)}
          onSave={onSaveApiUrl}
          onReset={onResetApiUrl}
        />
      )}

      <main className="page">
        <section className="row-hero">
          <div className="card hero-card">
            <div className="hero-grid">
              <div className="hero-left">
                <div className="hero-label">
                  <Ic d={ICON.clock} size={12} sw={2} />
                  account value · {market}
                </div>
                <div className="hero-value ds-num">{fmtUsd(account?.total_value)}</div>
                <HeroDelta delta={totalPnlSinceInitial} pct={pctSinceInitial} initial={account?.initial_balance ?? null} />
                <div className="hero-meta">
                  {todaysChange
                    ? `today ${fmtUsdSign(todaysChange.delta)} (${fmtPctSign(todaysChange.pct)})`
                    : `today —`}
                  {cycle != null ? ` · cycle ${cycle}` : ""}
                </div>
              </div>

              <div className="hero-right">
                <div className="mini-kpi">
                  <div className="lbl">open p&amp;l</div>
                  <div className={`val ${openUnrealPnl >= 0 ? "ds-profit" : "ds-loss"}`}>
                    {fmtUsdSign(openUnrealPnl)}
                  </div>
                  <div className="sub">unrealized · {visiblePositions.length} pos</div>
                </div>
                <div className="mini-kpi">
                  <div className="lbl">realized 7d</div>
                  <div className={`val ${realized7d.sum >= 0 ? "ds-profit" : "ds-loss"}`}>
                    {fmtUsdSign(realized7d.sum)}
                  </div>
                  <div className="sub">
                    {realized7d.n} closed{realized7d.winPct != null ? ` · ${realized7d.winPct}% win` : ""}
                  </div>
                </div>
                <div className="mini-kpi">
                  <div className="lbl">exposure</div>
                  <div className="val">
                    {exposure ? exposure.totalPct.toFixed(1) : "—"}
                    <span style={{ color: "var(--fg-2)", fontSize: 13 }}>%</span>
                  </div>
                  <div className="sub">
                    {exposure ? `limit 50% · ${(50 - exposure.totalPct).toFixed(1)}% headroom` : "limit 50%"}
                  </div>
                </div>
                <div className="mini-kpi">
                  <div className="lbl">drawdown</div>
                  <div className={`val ${drawdown != null && drawdown < -2 ? "ds-warn" : ""}`}>
                    {drawdown != null ? `${drawdown.toFixed(2)}%` : "—"}
                  </div>
                  <div className="sub">circuit at -10%</div>
                </div>
              </div>
            </div>

            <EquityChart
              points={equity}
              range={range}
              setRange={setRange}
              initial={account?.initial_balance ?? null}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="card">
              <div className="card-head">
                <h3>market</h3>
                <span className="ds-meta ds-mono">
                  {(positionsByMarket.crypto > 0 ? 1 : 0) + (positionsByMarket.stocks > 0 ? 1 : 0)} active
                </span>
              </div>
              <div className="card-body" style={{ padding: 16 }}>
                <div
                  className="segmented"
                  style={{ width: "100%", display: "grid", gridTemplateColumns: "1fr 1fr 1fr" }}
                >
                  <button className={market === "combined" ? "active" : ""} onClick={() => setMarket("combined")}>
                    combined <span className="count">{positionsByMarket.combined}</span>
                  </button>
                  <button className={market === "crypto" ? "active" : ""} onClick={() => setMarket("crypto")}>
                    crypto <span className="count">{positionsByMarket.crypto}</span>
                  </button>
                  <button
                    className={market === "stocks" ? "active" : ""}
                    disabled={!stocksOk}
                    onClick={() => stocksOk && setMarket("stocks")}
                  >
                    stocks <span className="count">{positionsByMarket.stocks}</span>
                  </button>
                </div>

                <MarketSplit combined={combined} positions={allPositions} totalValue={account?.total_value ?? 0} />
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <h3>exposure · {exposure ? `${exposure.totalPct.toFixed(1)}%` : "—"}</h3>
                <span className="ds-meta ds-mono">limit 50%</span>
              </div>
              <div className="card-body">
                <div className="exposure">
                  <ExposureRow label="crypto" pct={exposure?.cryptoPct ?? 0} fillClass="crypto" showLimit />
                  <ExposureRow label="stocks" pct={exposure?.stocksPct ?? 0} fillClass="stocks" showLimit />
                  <ExposureRow label="cash" pct={exposure?.cashPct ?? 100} fillClass="cash" />
                </div>
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 14,
                    borderTop: "1px solid var(--border-1)",
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 12,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--fg-2)",
                  }}
                >
                  <div>max position <span style={{ color: "var(--fg-0)" }}>10%</span></div>
                  <div>max leverage <span style={{ color: "var(--fg-0)" }}>3.0×</span></div>
                  <div>daily DD <span style={{ color: "var(--fg-0)" }}>-10%</span></div>
                  <div>SL mandatory <span style={{ color: "var(--fg-0)" }}>5%</span></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="row-main">
          <div className="card">
            <div className="card-head">
              <h3>open positions · {visiblePositions.length}</h3>
              <span className="ds-meta ds-mono">
                unreal. p&amp;l{" "}
                <span className={openUnrealPnl >= 0 ? "ds-profit" : "ds-loss"}>{fmtUsdSign(openUnrealPnl)}</span>
              </span>
            </div>
            <div className="card-flush">
              {visiblePositions.length === 0 ? (
                <Empty title="no open positions" body="the agent will open trades on the next cycle when conditions align." />
              ) : (
                <div className="table-scroll">
                  <table className="t">
                    <thead>
                      <tr>
                        <th>asset</th>
                        <th>side</th>
                        <th className="num">size</th>
                        <th className="num">entry</th>
                        <th className="num">mark</th>
                        <th className="num">unreal. p&amp;l</th>
                        <th>sl ←→ tp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visiblePositions.map((p) => {
                        const isLong = p.szi > 0;
                        const mark = p.entryPx + (Math.abs(p.szi) > 0 ? p.pnl / p.szi : 0);
                        return (
                          <tr key={`${p.market}-${p.coin}`}>
                            <td>
                              <span className="asset">
                                <span className={`pill ${p.market}`}>{assetGlyph(p.market)}</span>
                                <span>{p.coin}</span>
                              </span>
                            </td>
                            <td>
                              <span className={`pill ${isLong ? "long" : "short"}`}>{isLong ? "long" : "short"}</span>
                            </td>
                            <td className="num">{fmtSize(Math.abs(p.szi), p.market)}</td>
                            <td className="num">{fmtUsd(p.entryPx)}</td>
                            <td className="num">{fmtUsd(mark)}</td>
                            <td className={`num ${p.pnl >= 0 ? "ds-profit" : "ds-loss"}`}>
                              {fmtUsdSign(p.pnl)}
                            </td>
                            <td>
                              <Ladder pos={p} mark={mark} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>recent decisions · {decisions.length}</h3>
              <span className="ds-meta ds-mono">{cycle != null ? `cycle ${cycle}` : "—"}</span>
            </div>
            {decisions.length === 0 ? (
              <Empty title="waiting for first cycle" body="the agent runs once an hour. decisions will stream in here." />
            ) : (
              <div className="feed">
                {decisions.slice(0, 8).map((d, i) => {
                  const m = d.market ?? "crypto";
                  const action = d.action ?? "hold";
                  return (
                    <div key={i} className="item">
                      <div className="stamp">
                        <span className="cycle">#{d.cycle}</span>
                        {(d.timestamp ?? "").slice(11, 19) || "—"}
                      </div>
                      <div className="body">
                        <div className="head">
                          <span className={`pill ${m}`}>{assetGlyph(m)}</span>
                          <span className="asset-mark">{d.asset.replace("-PERP", "")}</span>
                          <span className={`action ${action}`}>{action}</span>
                        </div>
                        <div className="rationale">{d.rationale || "—"}</div>
                      </div>
                      <div
                        className="alloc"
                        style={action === "hold" ? { color: "var(--fg-3)" } : undefined}
                      >
                        {action === "hold" ? "—" : fmtUsd(d.allocation_usd)}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <section className="row-main">
          <div className="card">
            <div className="card-head">
              <h3>
                closed trades · {tradeRange === "ALL" ? "all" : `last ${tradeRange.toLowerCase()}`}
              </h3>
              <div className="range-tabs">
                {(["1D", "7D", "30D", "ALL"] as const).map((r) => (
                  <button key={r} className={tradeRange === r ? "active" : ""} onClick={() => setTradeRange(r)}>
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div className="card-flush">
              {filteredTrades.length === 0 ? (
                <Empty title="no closed trades in window" body="widen the range to see older fills." />
              ) : (
                <div className="table-scroll">
                  <table className="t">
                    <thead>
                      <tr>
                        <th>closed</th>
                        <th>asset</th>
                        <th>side</th>
                        <th className="num">entry</th>
                        <th className="num">exit</th>
                        <th>reason</th>
                        <th className="num">realized p&amp;l</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTrades.map((t) => {
                        const m = t.market ?? "crypto";
                        return (
                          <tr key={t.id}>
                            <td className="ds-num-sm">
                              {t.closed_at?.slice(0, 16).replace("T", " ") ?? "—"}
                            </td>
                            <td>
                              <span className="asset">
                                <span className={`pill ${m}`}>{assetGlyph(m)}</span>
                                {t.asset}
                              </span>
                            </td>
                            <td>
                              <span className={`pill ${t.side === "long" ? "long" : "short"}`}>{t.side}</span>
                            </td>
                            <td className="num">{fmtUsd(t.entry_price)}</td>
                            <td className="num">{fmtUsd(t.close_price)}</td>
                            <td>
                              <span className="pill hold">{t.close_reason ?? "—"}</span>
                            </td>
                            <td className={`num ${(t.realized_pnl ?? 0) >= 0 ? "ds-profit" : "ds-loss"}`}>
                              {fmtUsdSign(t.realized_pnl)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>stocks{!stocksOk ? " · offline" : ""}</h3>
              <span className={`ds-meta ds-mono${!stocksOk ? " ds-warn" : ""}`}>
                {!stocksOk ? "paused" : `${positionsByMarket.stocks} open`}
              </span>
            </div>
            {!stocksOk ? (
              <div className="empty">
                <div className="icon-wrap">
                  <Ic d={ICON.inbox} size={20} sw={1.5} />
                </div>
                <h4>stocks bot is not reporting</h4>
                <p>
                  the alpaca worker hasn&apos;t pinged. existing positions are mark-to-market only.
                  bring it back with <code>start-stocks.bat</code>.
                </p>
              </div>
            ) : (
              <div className="card-body">
                <div className="ds-meta">{positionsByMarket.stocks} stock positions running.</div>
              </div>
            )}
          </div>
        </section>

        <div className="foot">
          paper mode<span className="sep">·</span>refreshes every 10s
          <span className="sep">·</span>
          {visiblePositions.length} open position{visiblePositions.length === 1 ? "" : "s"}
          {cycle != null ? <><span className="sep">·</span>cycle {cycle}</> : null}
          <span className="sep">·</span>
          <button className="link-foot" onClick={() => setShowFix(true)} title="change api url">
            {apiUrl || "—"}
          </button>
        </div>
      </main>
    </div>
  );
}

/* ---------- subcomponents ---------- */

function HeroDelta({
  delta,
  pct,
  initial,
}: {
  delta: number | null;
  pct: number | null;
  initial: number | null;
}) {
  if (delta == null || pct == null) {
    return (
      <div className="hero-delta">
        <span className="ds-fg-2">awaiting first snapshot</span>
      </div>
    );
  }
  const up = delta >= 0;
  return (
    <div className={`hero-delta ${up ? "up" : "down"}`}>
      <Ic d={up ? ICON.arrowUpRight : ICON.arrowDownRight} size={12} sw={2.25} />
      {fmtUsdSign(delta)}
      <span className="pill">{fmtPctSign(pct)}</span>
      {initial != null && <span className="since">since {fmtUsd(initial)} initial</span>}
    </div>
  );
}

function ExposureRow({
  label,
  pct,
  fillClass,
  showLimit,
}: {
  label: string;
  pct: number;
  fillClass: "crypto" | "stocks" | "cash";
  showLimit?: boolean;
}) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div className="row">
      <span className="label">{label}</span>
      <div className="bar">
        <div className={`fill ${fillClass}`} style={{ width: `${w}%` }} />
        {showLimit && <div className="limit" style={{ left: "50%" }} />}
      </div>
      <span className="pct">{w.toFixed(1)}%</span>
    </div>
  );
}

function MarketSplit({
  combined,
  positions,
  totalValue,
}: {
  combined: Combined | null;
  positions: PositionTagged[];
  totalValue: number;
}) {
  const split = useMemo(() => {
    let cryptoNotional = 0;
    let stocksNotional = 0;
    let cryptoPnl = 0;
    let stocksPnl = 0;
    let cryptoOpen = 0;
    let stocksOpen = 0;
    for (const p of positions) {
      const mark = p.entryPx + (Math.abs(p.szi) > 0 ? p.pnl / p.szi : 0);
      const notional = Math.abs(p.szi) * mark;
      if (p.market === "crypto") {
        cryptoNotional += notional;
        cryptoPnl += p.pnl;
        cryptoOpen += 1;
      } else {
        stocksNotional += notional;
        stocksPnl += p.pnl;
        stocksOpen += 1;
      }
    }
    const cryptoVal = combined?.crypto.total_value ?? cryptoNotional;
    const stocksVal = combined?.stocks?.total_value ?? stocksNotional;
    return { cryptoVal, stocksVal, cryptoPnl, stocksPnl, cryptoOpen, stocksOpen };
  }, [positions, combined]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 1,
        marginTop: 12,
        background: "var(--border-1)",
        border: "1px solid var(--border-1)",
        borderRadius: "var(--r-md)",
        overflow: "hidden",
      }}
    >
      <div style={{ background: "var(--bg-1)", padding: 12 }}>
        <div className="ds-label" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="pill crypto">₿ crypto</span>
        </div>
        <div style={{ marginTop: 8 }} className="ds-num-lg">
          {fmtUsd(split.cryptoVal)}
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            marginTop: 2,
            color: split.cryptoPnl >= 0 ? "var(--profit)" : "var(--loss)",
          }}
        >
          {fmtUsdSign(split.cryptoPnl)} · {split.cryptoOpen} open
        </div>
      </div>
      <div style={{ background: "var(--bg-1)", padding: 12 }}>
        <div className="ds-label" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="pill stocks">stocks</span>
        </div>
        <div style={{ marginTop: 8 }} className="ds-num-lg">
          {combined?.stocks ? fmtUsd(split.stocksVal) : "—"}
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            marginTop: 2,
            color: split.stocksPnl >= 0 ? "var(--profit)" : "var(--fg-2)",
          }}
        >
          {split.stocksOpen === 0 ? "— · 0 open" : `${fmtUsdSign(split.stocksPnl)} · ${split.stocksOpen} open`}
        </div>
      </div>
    </div>
  );
}

function Ladder({ pos, mark }: { pos: Position; mark: number }) {
  const isLong = pos.szi > 0;
  const tp = pos.tp_price;
  const sl = pos.sl_price;
  let pct = 0;
  let direction: "up" | "down" = "up";
  if (tp && sl && pos.entryPx) {
    if (mark >= pos.entryPx) {
      const target = isLong ? tp : sl;
      const span = Math.abs(target - pos.entryPx);
      pct = span > 0 ? Math.min(50, (Math.abs(mark - pos.entryPx) / span) * 50) : 0;
      direction = isLong ? "up" : "down";
    } else {
      const target = isLong ? sl : tp;
      const span = Math.abs(target - pos.entryPx);
      pct = span > 0 ? Math.min(50, (Math.abs(mark - pos.entryPx) / span) * 50) : 0;
      direction = isLong ? "down" : "up";
    }
  }
  return (
    <div className="ladder">
      <div className={`fill ${direction === "down" ? "down" : ""}`} style={{ width: `${pct}%` }} />
      <div className="midline" />
      <div className="marker" style={{ left: 0 }} />
      <div className="marker" style={{ left: "100%" }} />
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty">
      <div className="icon-wrap">
        <Ic d={ICON.inbox} size={20} sw={1.5} />
      </div>
      <h4>{title}</h4>
      <p>{body}</p>
    </div>
  );
}

/* ---------- equity chart ---------- */

function EquityChart({
  points,
  range,
  setRange,
  initial,
}: {
  points: EquityPoint[];
  range: Range;
  setRange: (r: Range) => void;
  initial: number | null;
}) {
  const W = 800;
  const H = 220;
  const padL = 40;
  const padR = 20;
  const padT = 20;
  const padB = 40;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const cutoff = Date.now() - RANGE_MS[range];
  const series = useMemo(() => points.filter((p) => p.t >= cutoff), [points, cutoff]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);

  const { areaD, lineD, baselineY, vMin, vMax, line } = useMemo(() => {
    if (series.length < 2) {
      return { areaD: "", lineD: "", baselineY: null as number | null, vMin: 0, vMax: 0, line: [] as { x: number; y: number; v: number; t: number }[] };
    }
    const ts = series.map((p) => p.t);
    const vs = series.map((p) => p.v);
    const tMin = ts[0];
    const tMax = ts[ts.length - 1];
    let lo = Math.min(...vs);
    let hi = Math.max(...vs);
    if (initial != null) {
      lo = Math.min(lo, initial);
      hi = Math.max(hi, initial);
    }
    const pad = (hi - lo) * 0.1 || hi * 0.001 || 1;
    lo -= pad;
    hi += pad;

    const x = (t: number) =>
      padL + (tMax === tMin ? innerW : ((t - tMin) / (tMax - tMin)) * innerW);
    const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * innerH;

    const line = series.map((p) => ({ x: x(p.t), y: y(p.v), v: p.v, t: p.t }));
    let lineD = "";
    line.forEach((p, i) => {
      lineD += (i === 0 ? "M" : "L") + p.x.toFixed(1) + " " + p.y.toFixed(1) + " ";
    });
    let areaD = `M ${line[0].x.toFixed(1)} ${(padT + innerH).toFixed(1)} `;
    line.forEach((p) => {
      areaD += "L " + p.x.toFixed(1) + " " + p.y.toFixed(1) + " ";
    });
    areaD += `L ${line[line.length - 1].x.toFixed(1)} ${(padT + innerH).toFixed(1)} Z`;
    const baselineY = initial != null ? y(initial) : null;
    return { areaD, lineD, baselineY, vMin: lo, vMax: hi, line };
  }, [series, initial, innerH, innerW]);

  const isDown = series.length >= 2 && series[series.length - 1].v < series[0].v;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (line.length < 2 || !containerRef.current) return;
    const r = containerRef.current.getBoundingClientRect();
    const px = e.clientX - r.left;
    const ratio = (px / r.width) * W;
    let bestI = 0;
    let bestD = Number.POSITIVE_INFINITY;
    for (let i = 0; i < line.length; i++) {
      const d = Math.abs(line[i].x - ratio);
      if (d < bestD) {
        bestD = d;
        bestI = i;
      }
    }
    const lp = line[bestI];
    setHover({ i: bestI, x: (lp.x / W) * r.width, y: (lp.y / H) * r.height });
  }
  function onLeave() {
    setHover(null);
  }

  return (
    <div className="equity-wrap">
      <div className="equity-toolbar">
        <div className="legend">
          <span><span className="swatch" style={{ background: "var(--profit)" }}></span>jarvis equity</span>
          {initial != null && (
            <span><span className="swatch" style={{ background: "var(--border-2)" }}></span>initial baseline</span>
          )}
        </div>
        <div className="range-tabs">
          {(["1H", "1D", "1W", "ALL"] as const).map((r) => (
            <button key={r} className={range === r ? "active" : ""} onClick={() => setRange(r)}>
              {r}
            </button>
          ))}
        </div>
      </div>
      <div className="chart" ref={containerRef} onMouseMove={onMove} onMouseLeave={onLeave}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id="eq-fade" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#22D88F" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#22D88F" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="eq-fade-loss" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#FF5C6A" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#FF5C6A" stopOpacity="0" />
            </linearGradient>
          </defs>
          <g className="yaxis">
            {[0.2, 0.4, 0.6, 0.8].map((f, i) => (
              <line key={i} className="gridline" x1={padL} x2={W - padR} y1={padT + f * innerH} y2={padT + f * innerH} />
            ))}
            {series.length >= 2 && (
              <>
                <text x={padL - 6} y={padT + 4} textAnchor="end">{fmtUsdShort(vMax)}</text>
                <text x={padL - 6} y={padT + innerH + 4} textAnchor="end">{fmtUsdShort(vMin)}</text>
              </>
            )}
            {baselineY != null && (
              <line className="baseline" x1={padL} x2={W - padR} y1={baselineY} y2={baselineY} />
            )}
          </g>
          {areaD && <path className={isDown ? "area-loss" : "area-equity"} d={areaD} />}
          {lineD && <path className={`line-equity${isDown ? " down" : ""}`} d={lineD} />}
          {hover && (
            <line
              className="crosshair-v"
              x1={line[hover.i].x}
              x2={line[hover.i].x}
              y1={padT}
              y2={padT + innerH}
            />
          )}
        </svg>
        {series.length < 2 && (
          <div className="chart-empty">collecting equity samples · refreshes every 10s</div>
        )}
        {hover && (
          <div className="tooltip on" style={{ left: hover.x, top: hover.y }}>
            <div className="tt-time">
              {new Date(line[hover.i].t).toLocaleString("en-US", {
                month: "short",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              })}
            </div>
            <div className="tt-row">
              <span className="tt-label">value</span>
              <span className={isDown ? "ds-loss" : "ds-profit"}>{fmtUsd(line[hover.i].v)}</span>
            </div>
            {initial != null && (
              <div className="tt-row">
                <span className="tt-label">vs initial</span>
                <span>{fmtUsdSign(line[hover.i].v - initial)}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function fmtUsdShort(n: number) {
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(2)}k`;
  return `$${n.toFixed(2)}`;
}

/* ---------- fix-api dialog ---------- */
function FixApiDialog({
  current,
  onClose,
  onSave,
  onReset,
}: {
  current: string;
  onClose: () => void;
  onSave: (url: string) => void;
  onReset: () => void;
}) {
  const [value, setValue] = useState(current);
  const [probing, setProbing] = useState<null | string>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const sameOrigin =
    typeof window !== "undefined" ? `${window.location.protocol}//${window.location.host}` : "";

  const candidates = useMemo(() => {
    const list: string[] = [];
    if (sameOrigin) list.push(sameOrigin);
    list.push("https://rajputdev77.duckdns.org/trading/crypto");
    list.push("http://localhost:8000");
    list.push("http://127.0.0.1:8000");
    return Array.from(new Set(list.filter(Boolean)));
  }, [sameOrigin]);

  async function probe(url: string) {
    setProbing(url);
    setResult(null);
    const r = await probeApi(url);
    setProbing(null);
    setResult(r);
    return r;
  }

  async function autoFix() {
    setResult(null);
    for (const url of candidates) {
      const r = await probe(url);
      if (r.ok) {
        onSave(url);
        return;
      }
    }
    setResult({ ok: false, message: "none of the candidates responded — paste the api url manually" });
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>fix api connection</h3>
          <button className="btn-ghost" onClick={onClose}>close</button>
        </div>
        <div className="modal-body">
          <p className="ds-meta" style={{ marginTop: 0 }}>
            the dashboard polls a fastapi server. if the server isn&apos;t reachable at the saved url,
            you&apos;ll see an error. set the right url here once and it persists in your browser.
          </p>

          <label className="ds-label" style={{ display: "block", marginTop: 12 }}>api url</label>
          <input
            className="input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="https://rajputdev77.duckdns.org/trading/crypto"
            spellCheck={false}
            autoFocus
          />

          {candidates.length > 0 && (
            <>
              <div className="ds-label" style={{ marginTop: 14 }}>quick picks</div>
              <div className="chips">
                {candidates.map((c) => (
                  <button key={c} className="chip" onClick={() => setValue(c)}>{c}</button>
                ))}
              </div>
            </>
          )}

          {result && (
            <div className={`probe-result ${result.ok ? "ok" : "bad"}`}>
              {result.ok ? "✓ reachable" : `✗ ${result.message}`}
            </div>
          )}
          {probing && <div className="probe-result">probing {probing}…</div>}
        </div>
        <div className="modal-foot">
          <button className="btn-ghost" onClick={onReset} title="forget saved url, use defaults">reset</button>
          <div style={{ flex: 1 }} />
          <button className="btn-ghost" onClick={autoFix} disabled={probing != null} title="probe candidates and save the first one that works">
            auto-detect
          </button>
          <button className="btn-ghost" disabled={!value || probing != null} onClick={() => probe(value)}>
            test
          </button>
          <button
            className="btn-primary"
            disabled={!value || probing != null}
            onClick={async () => {
              const r = await probe(value);
              if (r.ok) onSave(value);
            }}
          >
            save &amp; retry
          </button>
        </div>
      </div>
    </div>
  );
}
