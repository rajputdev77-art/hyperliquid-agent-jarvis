"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  Account,
  Combined,
  Decision,
  Market,
  Position,
  Trade,
  API_URL,
} from "@/lib/api";

type DecisionTagged = Decision & { market?: "crypto" | "stocks" };
type TradeTagged = Trade & { market?: "crypto" | "stocks" };

const fmtUsd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : `$${n.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;

const fmtPct = (base: number, now: number) =>
  base > 0 ? `${(((now - base) / base) * 100).toFixed(2)}%` : "—";

const MARKETS: { key: Market; label: string; emoji: string; accent: string }[] = [
  { key: "combined", label: "Combined", emoji: "🌐", accent: "from-cyan-400 to-fuchsia-400" },
  { key: "crypto",   label: "Crypto",   emoji: "₿",  accent: "from-amber-400 to-orange-500" },
  { key: "stocks",   label: "Stocks",   emoji: "📈", accent: "from-emerald-400 to-green-500" },
];

export default function Home() {
  const [market, setMarket] = useState<Market>("combined");
  const [account, setAccount] = useState<Account | null>(null);
  const [combined, setCombined] = useState<Combined | null>(null);
  const [positions, setPositions] = useState<{ crypto: Position[]; stocks: Position[] } | null>(null);
  const [trades, setTrades] = useState<TradeTagged[]>([]);
  const [decisions, setDecisions] = useState<DecisionTagged[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [stocksOk, setStocksOk] = useState(false);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const h = await api.health();
        if (!alive) return;
        setStocksOk(!!h.stocks_db);

        if (market === "combined") {
          const [c, p, t, d] = await Promise.all([
            api.account("combined") as Promise<Combined>,
            api.positionsBoth(),
            api.historyBoth(50),
            api.decisionsBoth(20),
          ]);
          if (!alive) return;
          setCombined(c);
          setAccount(c.total);
          setPositions(p);
          setTrades(t.trades);
          setDecisions(d.decisions);
        } else {
          const [a, p, t, d] = await Promise.all([
            api.account(market) as Promise<Account>,
            api.positions(market),
            api.history(market, 50),
            api.decisions(market, 20),
          ]);
          if (!alive) return;
          setAccount(a);
          setCombined(null);
          setPositions(market === "crypto" ? { crypto: p.positions, stocks: [] } : { crypto: [], stocks: p.positions });
          setTrades(t.trades.map((x) => ({ ...x, market } as TradeTagged)));
          setDecisions(d.decisions.map((x) => ({ ...x, market } as DecisionTagged)));
        }
        setUpdated(new Date());
        setErr(null);
      } catch (e: unknown) {
        if (alive) setErr(e instanceof Error ? e.message : "fetch error");
      }
    };
    pull();
    const t = setInterval(pull, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [market]);

  const allPositions: (Position & { market: "crypto" | "stocks" })[] = useMemo(() => {
    if (!positions) return [];
    return [
      ...positions.crypto.map((p) => ({ ...p, market: "crypto" as const })),
      ...positions.stocks.map((p) => ({ ...p, market: "stocks" as const })),
    ];
  }, [positions]);

  const visiblePositions =
    market === "combined"
      ? allPositions
      : allPositions.filter((p) => p.market === market);

  return (
    <main className="min-h-screen bg-gradient-to-br from-[#0a0a14] via-[#0d0f1c] to-[#1a0a1f] text-neutral-100">
      <div className="mx-auto max-w-6xl p-6 space-y-6">
        {/* Header */}
        <header className="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 border-b border-white/5 pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-cyan-300 via-fuchsia-300 to-amber-300 bg-clip-text text-transparent">
              jarvis
            </h1>
            <p className="text-xs text-neutral-500">
              gemini-2.5-flash-lite · paper mode · hyperliquid + alpaca
            </p>
          </div>
          <div className="text-right text-xs text-neutral-500">
            {updated && (
              <div className="flex items-center gap-2 justify-end">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                live · updated {updated.toLocaleTimeString()}
              </div>
            )}
            <div className="text-neutral-700 truncate max-w-xs">{API_URL}</div>
          </div>
        </header>

        {/* Market toggle */}
        <div className="flex gap-2 p-1 bg-white/5 rounded-xl backdrop-blur-sm border border-white/10 w-fit">
          {MARKETS.map((m) => {
            const disabled = m.key === "stocks" && !stocksOk;
            const active = market === m.key;
            return (
              <button
                key={m.key}
                onClick={() => !disabled && setMarket(m.key)}
                disabled={disabled}
                className={`relative px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  active
                    ? `text-white shadow-lg`
                    : disabled
                    ? "text-neutral-600 cursor-not-allowed"
                    : "text-neutral-400 hover:text-neutral-200"
                }`}
              >
                {active && (
                  <span
                    className={`absolute inset-0 rounded-lg bg-gradient-to-r ${m.accent} opacity-90 -z-0`}
                  />
                )}
                <span className="relative z-10">
                  {m.emoji} {m.label}
                  {disabled && <span className="ml-1 text-[10px]">(offline)</span>}
                </span>
              </button>
            );
          })}
        </div>

        {err && (
          <div className="rounded-lg border border-red-900/50 bg-red-950/40 p-3 text-sm text-red-300 backdrop-blur">
            {err}
          </div>
        )}

        {/* Stat cards */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="account value" value={fmtUsd(account?.total_value)} icon="💰" />
          <Stat
            label="return"
            value={account ? fmtPct(account.initial_balance, account.total_value) : "—"}
            tone={account && account.total_value >= account.initial_balance ? "good" : "bad"}
            icon="📊"
          />
          <Stat
            label="total pnl"
            value={fmtUsd(account?.total_pnl)}
            tone={(account?.total_pnl ?? 0) >= 0 ? "good" : "bad"}
            icon={account && account.total_pnl >= 0 ? "🟢" : "🔴"}
          />
          <Stat
            label="open positions"
            value={String(account?.open_positions ?? 0)}
            icon="📍"
          />
        </section>

        {/* Combined sub-stats */}
        {market === "combined" && combined && (
          <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <SubAccountCard label="Crypto" emoji="₿" account={combined.crypto} accent="amber" />
            {combined.stocks ? (
              <SubAccountCard label="Stocks" emoji="📈" account={combined.stocks} accent="emerald" />
            ) : (
              <div className="rounded-xl border border-dashed border-white/10 p-4 text-xs text-neutral-600 flex items-center justify-center">
                Stocks bot offline — start it with{" "}
                <code className="bg-white/5 px-2 py-0.5 rounded ml-1">start-stocks.bat</code>
              </div>
            )}
          </section>
        )}

        {/* Positions */}
        <Section title={`open positions · ${visiblePositions.length}`}>
          {visiblePositions.length === 0 ? (
            <Empty text="no open positions" />
          ) : (
            <Table
              cols={
                market === "combined"
                  ? ["market", "asset", "side", "size", "entry", "unreal. pnl", "tp", "sl"]
                  : ["asset", "side", "size", "entry", "unreal. pnl", "tp", "sl"]
              }
              rows={visiblePositions.map((p) => {
                const cells: (string | JSX.Element)[] = [
                  p.coin,
                  <Pill key="s" tone={p.szi > 0 ? "long" : "short"}>
                    {p.szi > 0 ? "long" : "short"}
                  </Pill>,
                  Math.abs(p.szi).toFixed(p.market === "stocks" ? 3 : 6),
                  p.entryPx.toFixed(2),
                  <span key="pnl" className={p.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                    {fmtUsd(p.pnl)}
                  </span>,
                  p.tp_price?.toFixed(2) ?? "—",
                  p.sl_price?.toFixed(2) ?? "—",
                ];
                if (market === "combined") cells.unshift(<MarketBadge key="m" market={p.market} />);
                return cells;
              })}
            />
          )}
        </Section>

        {/* Trades */}
        <Section title={`recent trades · ${trades.length}`}>
          {trades.length === 0 ? (
            <Empty text="no closed trades yet" />
          ) : (
            <Table
              cols={
                market === "combined"
                  ? ["market", "closed", "asset", "side", "entry", "exit", "reason", "pnl"]
                  : ["closed", "asset", "side", "entry", "exit", "reason", "pnl"]
              }
              rows={trades.map((t) => {
                const cells: (string | JSX.Element)[] = [
                  t.closed_at?.slice(0, 19).replace("T", " ") ?? "—",
                  t.asset,
                  <Pill key="s" tone={t.side as "long" | "short"}>{t.side}</Pill>,
                  t.entry_price.toFixed(2),
                  t.close_price?.toFixed(2) ?? "—",
                  t.close_reason ?? "—",
                  <span key="r" className={(t.realized_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}>
                    {fmtUsd(t.realized_pnl ?? 0)}
                  </span>,
                ];
                if (market === "combined") cells.unshift(<MarketBadge key="m" market={t.market ?? "crypto"} />);
                return cells;
              })}
            />
          )}
        </Section>

        {/* Decisions */}
        <Section title={`recent decisions · ${decisions.length}`}>
          {decisions.length === 0 ? (
            <Empty text="waiting for first cycle" />
          ) : (
            <ul className="space-y-3">
              {decisions.map((d, i) => (
                <li
                  key={i}
                  className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-sm backdrop-blur-sm hover:border-white/10 transition"
                >
                  <div className="flex items-center justify-between text-xs text-neutral-500 mb-2">
                    <div className="flex items-center gap-2">
                      {d.market && <MarketBadge market={d.market} />}
                      <span>cycle {d.cycle}</span>
                      <span>·</span>
                      <span>{d.timestamp?.slice(0, 19).replace("T", " ")}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`uppercase font-semibold tracking-wide ${
                          d.action === "buy"
                            ? "text-emerald-400"
                            : d.action === "sell"
                            ? "text-red-400"
                            : "text-neutral-500"
                        }`}
                      >
                        {d.action}
                      </span>
                      <span className="text-neutral-300">{d.asset}</span>
                      {d.action !== "hold" && (
                        <span className="text-cyan-400">{fmtUsd(d.allocation_usd)}</span>
                      )}
                    </div>
                  </div>
                  <p className="text-neutral-200">{d.rationale}</p>
                  {d.exit_plan && (
                    <p className="mt-2 text-xs text-neutral-500">
                      <span className="text-neutral-400">exit plan: </span>
                      {d.exit_plan}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <footer className="pt-6 pb-4 text-center text-xs text-neutral-700">
          paper mode · refreshes every 10s · {visiblePositions.length} open
        </footer>
      </div>
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
  icon,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
  icon?: string;
}) {
  return (
    <div className="relative rounded-xl border border-white/10 bg-white/[0.03] backdrop-blur-sm p-4 overflow-hidden group hover:border-white/20 transition">
      <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition" />
      <div className="relative">
        <div className="flex items-center justify-between text-xs uppercase tracking-wide text-neutral-500">
          <span>{label}</span>
          {icon && <span className="text-base">{icon}</span>}
        </div>
        <div
          className={`mt-2 text-xl font-semibold ${
            tone === "good"
              ? "text-emerald-400"
              : tone === "bad"
              ? "text-red-400"
              : "text-neutral-100"
          }`}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

function SubAccountCard({
  label,
  emoji,
  account,
  accent,
}: {
  label: string;
  emoji: string;
  account: Account;
  accent: "amber" | "emerald";
}) {
  const accentClass =
    accent === "amber"
      ? "from-amber-500/20 to-orange-500/10 border-amber-500/30"
      : "from-emerald-500/20 to-green-500/10 border-emerald-500/30";
  const pnlPositive = account.total_pnl >= 0;
  return (
    <div
      className={`rounded-xl border p-4 backdrop-blur-sm bg-gradient-to-br ${accentClass}`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{emoji}</span>
          <span className="font-semibold">{label}</span>
        </div>
        <span className="text-xs text-neutral-400">
          {account.open_positions} open
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs text-neutral-500">value</div>
          <div className="font-medium">{fmtUsd(account.total_value)}</div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">return</div>
          <div
            className={`font-medium ${
              account.total_value >= account.initial_balance ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {fmtPct(account.initial_balance, account.total_value)}
          </div>
        </div>
        <div>
          <div className="text-xs text-neutral-500">pnl</div>
          <div className={`font-medium ${pnlPositive ? "text-emerald-400" : "text-red-400"}`}>
            {fmtUsd(account.total_pnl)}
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-xs uppercase tracking-widest text-neutral-500 font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/10 p-6 text-xs text-neutral-600 text-center">
      {text}
    </div>
  );
}

function Table({
  cols,
  rows,
}: {
  cols: string[];
  rows: (string | number | JSX.Element)[][];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/10 bg-white/[0.02] backdrop-blur-sm">
      <table className="w-full text-xs">
        <thead className="bg-white/5 text-neutral-400">
          <tr>
            {cols.map((c) => (
              <th
                key={c}
                className="px-3 py-2.5 text-left font-medium uppercase tracking-wide"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className="border-t border-white/5 hover:bg-white/[0.03] transition"
            >
              {r.map((v, j) => (
                <td key={j} className="px-3 py-2.5">
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pill({
  tone,
  children,
}: {
  tone: "long" | "short";
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-semibold ${
        tone === "long"
          ? "bg-emerald-500/15 text-emerald-300"
          : "bg-red-500/15 text-red-300"
      }`}
    >
      {children}
    </span>
  );
}

function MarketBadge({ market }: { market: "crypto" | "stocks" }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-semibold ${
        market === "crypto"
          ? "bg-amber-500/15 text-amber-300"
          : "bg-emerald-500/15 text-emerald-300"
      }`}
    >
      {market === "crypto" ? "₿ crypto" : "📈 stocks"}
    </span>
  );
}
