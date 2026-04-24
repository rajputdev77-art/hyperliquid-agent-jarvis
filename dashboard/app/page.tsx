"use client";

import { useEffect, useState } from "react";
import { api, Account, Decision, Position, Trade, API_URL } from "@/lib/api";

const fmtUsd = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

const fmtPct = (base: number, now: number) =>
  base > 0 ? `${(((now - base) / base) * 100).toFixed(2)}%` : "—";

export default function Home() {
  const [account, setAccount] = useState<Account | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const [a, p, h, d] = await Promise.all([
          api.account(),
          api.positions(),
          api.history(50),
          api.decisions(20),
        ]);
        if (!alive) return;
        setAccount(a);
        setPositions(p.positions);
        setTrades(h.trades);
        setDecisions(d.decisions);
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
  }, []);

  return (
    <main className="mx-auto max-w-6xl p-6 space-y-6">
      <header className="flex items-center justify-between border-b border-neutral-800 pb-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">jarvis</h1>
          <p className="text-xs text-neutral-500">gemini-2.5-flash · paper mode · hyperliquid perps</p>
        </div>
        <div className="text-xs text-neutral-500">
          {updated && `updated ${updated.toLocaleTimeString()}`}
          <div className="text-neutral-700">{API_URL}</div>
        </div>
      </header>

      {err && (
        <div className="rounded border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
          error: {err}
        </div>
      )}

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="account value" value={fmtUsd(account?.total_value)} />
        <Stat
          label="return"
          value={account ? fmtPct(account.initial_balance, account.total_value) : "—"}
          tone={account && account.total_value >= account.initial_balance ? "good" : "bad"}
        />
        <Stat
          label="total pnl"
          value={fmtUsd(account?.total_pnl)}
          tone={(account?.total_pnl ?? 0) >= 0 ? "good" : "bad"}
        />
        <Stat
          label="daily pnl"
          value={fmtUsd(account?.daily_pnl)}
          tone={(account?.daily_pnl ?? 0) >= 0 ? "good" : "bad"}
        />
      </section>

      <Section title={`open positions (${positions.length})`}>
        {positions.length === 0 ? (
          <Empty text="no open positions" />
        ) : (
          <Table
            cols={["asset", "side", "size", "entry", "unreal. pnl", "tp", "sl"]}
            rows={positions.map((p) => [
              p.coin,
              p.szi > 0 ? "long" : "short",
              Math.abs(p.szi).toFixed(6),
              p.entryPx.toFixed(2),
              fmtUsd(p.pnl),
              p.tp_price?.toFixed(2) ?? "—",
              p.sl_price?.toFixed(2) ?? "—",
            ])}
          />
        )}
      </Section>

      <Section title={`recent trades (${trades.length})`}>
        {trades.length === 0 ? (
          <Empty text="no closed trades yet" />
        ) : (
          <Table
            cols={["closed", "asset", "side", "entry", "exit", "reason", "pnl"]}
            rows={trades.map((t) => [
              t.closed_at?.slice(0, 19).replace("T", " ") ?? "—",
              t.asset,
              t.side,
              t.entry_price.toFixed(2),
              t.close_price?.toFixed(2) ?? "—",
              t.close_reason ?? "—",
              fmtUsd(t.realized_pnl ?? 0),
            ])}
          />
        )}
      </Section>

      <Section title={`recent decisions (${decisions.length})`}>
        {decisions.length === 0 ? (
          <Empty text="waiting for first cycle" />
        ) : (
          <ul className="space-y-3">
            {decisions.map((d, i) => (
              <li key={i} className="rounded border border-neutral-900 p-3 text-sm">
                <div className="flex items-center justify-between text-xs text-neutral-500">
                  <span>cycle {d.cycle} · {d.timestamp?.slice(0, 19).replace("T", " ")}</span>
                  <span>
                    <span className={d.action === "buy" ? "text-emerald-400" : d.action === "sell" ? "text-red-400" : "text-neutral-500"}>
                      {d.action}
                    </span>{" "}
                    {d.asset}{" "}
                    {d.action !== "hold" && `· ${fmtUsd(d.allocation_usd)}`}
                  </span>
                </div>
                <p className="mt-2 text-neutral-300">{d.rationale}</p>
                {d.exit_plan && <p className="mt-1 text-xs text-neutral-500">exit plan: {d.exit_plan}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded border border-neutral-900 p-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div
        className={`mt-1 text-lg font-medium ${
          tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-red-400" : "text-neutral-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-sm uppercase tracking-wide text-neutral-500">{title}</h2>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded border border-dashed border-neutral-900 p-4 text-xs text-neutral-600">{text}</div>;
}

function Table({ cols, rows }: { cols: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto rounded border border-neutral-900">
      <table className="w-full text-xs">
        <thead className="bg-neutral-950 text-neutral-500">
          <tr>{cols.map((c) => <th key={c} className="px-3 py-2 text-left font-normal">{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-neutral-900">
              {r.map((v, j) => <td key={j} className="px-3 py-2">{v}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
