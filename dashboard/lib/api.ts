export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function j<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export type Account = {
  initial_balance: number;
  balance: number;
  total_value: number;
  total_pnl: number;
  daily_pnl: number;
  open_positions: number;
};

export type Position = {
  coin: string;
  szi: number;
  entryPx: number;
  pnl: number;
  leverage: number;
  tp_price: number | null;
  sl_price: number | null;
};

export type Trade = {
  id: number;
  asset: string;
  side: "long" | "short";
  size_asset: number;
  entry_price: number;
  close_price: number | null;
  tp_price: number | null;
  sl_price: number | null;
  opened_at: string;
  closed_at: string | null;
  close_reason: string | null;
  realized_pnl: number | null;
};

export type Decision = {
  timestamp: string;
  cycle: number;
  asset: string;
  action: "buy" | "sell" | "hold";
  allocation_usd: number;
  rationale: string;
  exit_plan: string;
  reasoning: string;
  account_value: number;
};

export type Combined = {
  crypto: Account;
  stocks: Account | null;
  total: Account;
};

export type Market = "crypto" | "stocks" | "combined";

const prefix = (m: Market) => (m === "stocks" ? "/stocks" : "");

export const api = {
  account: (m: Market) =>
    m === "combined"
      ? j<Combined>("/combined/account")
      : j<Account>(`${prefix(m)}/account`),
  positions: (m: Market) =>
    j<{ positions: Position[] }>(`${prefix(m === "combined" ? "crypto" : m)}/positions`),
  positionsBoth: async () => {
    const [c, s] = await Promise.all([
      j<{ positions: Position[] }>("/positions"),
      j<{ positions: Position[] }>("/stocks/positions").catch(() => ({ positions: [] })),
    ]);
    return {
      crypto: c.positions,
      stocks: s.positions,
    };
  },
  history: (m: Market, limit = 50) =>
    j<{ trades: Trade[] }>(`${prefix(m === "combined" ? "crypto" : m)}/history?limit=${limit}`),
  historyBoth: async (limit = 50) => {
    const [c, s] = await Promise.all([
      j<{ trades: Trade[] }>(`/history?limit=${limit}`),
      j<{ trades: Trade[] }>(`/stocks/history?limit=${limit}`).catch(() => ({ trades: [] })),
    ]);
    // tag and merge
    const tag = (rows: Trade[], market: "crypto" | "stocks") =>
      rows.map((t) => ({ ...t, market }));
    return {
      trades: [...tag(c.trades, "crypto"), ...tag(s.trades, "stocks")]
        .sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""))
        .slice(0, limit),
    };
  },
  decisions: (m: Market, limit = 20) =>
    j<{ decisions: Decision[] }>(
      `${prefix(m === "combined" ? "crypto" : m)}/decisions?limit=${limit}`,
    ),
  decisionsBoth: async (limit = 20) => {
    const [c, s] = await Promise.all([
      j<{ decisions: Decision[] }>(`/decisions?limit=${limit}`),
      j<{ decisions: Decision[] }>(`/stocks/decisions?limit=${limit}`).catch(() => ({
        decisions: [],
      })),
    ]);
    const tag = (rows: Decision[], market: "crypto" | "stocks") =>
      rows.map((d) => ({ ...d, market }));
    return {
      decisions: [...tag(c.decisions, "crypto"), ...tag(s.decisions, "stocks")]
        .sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""))
        .slice(0, limit),
    };
  },
  health: () => j<{ ok: boolean; stocks_db?: boolean }>("/health"),
};
