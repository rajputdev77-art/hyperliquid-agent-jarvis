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

export const api = {
  account: () => j<Account>("/account"),
  positions: () => j<{ positions: Position[] }>("/positions"),
  history: (limit = 200) => j<{ trades: Trade[] }>(`/history?limit=${limit}`),
  decisions: (limit = 50) => j<{ decisions: Decision[] }>(`/decisions?limit=${limit}`),
  health: () => j<{ ok: boolean }>("/health"),
};
