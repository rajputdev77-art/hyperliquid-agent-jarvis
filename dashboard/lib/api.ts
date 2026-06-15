// API base URL with click-to-fix support.
//
// Priority:
//   1. localStorage override ("jarvis.apiUrl") — set from the dashboard's "fix it" UI
//   2. build-time NEXT_PUBLIC_API_URL
//   3. cloudflared/loca.lt tunnel default for this project (when on a dashboard-only host)
//   4. same-origin fallback (when reverse-proxied)
//   5. http://localhost:8000 (local-dev default)
const API_KEY = "jarvis.apiUrl";
const BUILD_URL =
  typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_URL : undefined;
// Oracle Cloud VM behind nginx + Let's Encrypt — the canonical production endpoint.
// Previously a Cloudflare/loca.lt tunnel; migrated to permanent Oracle Cloud May 2026.
const TUNNEL_DEFAULT = "https://rajputdev77.duckdns.org/trading/crypto";

// Known-dead URLs that should be ignored if they appear in localStorage from a
// previous session. When a browser still holds one of these, fall through to
// the env-var / TUNNEL_DEFAULT instead of trying the dead host.
const DEAD_URL_PATTERNS = [
  /jarvis-trading\.loca\.lt/i,
  /\.trycloudflare\.com/i,
  /^https?:\/\/localhost(:|$)/i,   // dead on a hosted dashboard
  /^https?:\/\/127\.0\.0\.1(:|$)/i,
];

function isDeadUrl(url: string): boolean {
  if (typeof window === "undefined") return false;
  const onHostedDashboard = /vercel\.app$|netlify\.app$|pages\.dev$/.test(window.location.host);
  return DEAD_URL_PATTERNS.some((re) => {
    // localhost is only "dead" when we're on a hosted dashboard
    if ((re.source.includes("localhost") || re.source.includes("127")) && !onHostedDashboard) {
      return false;
    }
    return re.test(url);
  });
}

function readLocal(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(API_KEY);
    if (!v) return null;
    if (isDeadUrl(v)) {
      // Auto-heal: drop the stale URL so we fall through to env / default
      window.localStorage.removeItem(API_KEY);
      return null;
    }
    return v;
  } catch {
    return null;
  }
}

export function getApiUrl(): string {
  const local = readLocal();
  if (local) return local.replace(/\/+$/, "");
  if (BUILD_URL) return BUILD_URL.replace(/\/+$/, "");
  if (typeof window !== "undefined") {
    const { protocol, host } = window.location;
    const isDashboardOnlyHost = /vercel\.app$|netlify\.app$|pages\.dev$/.test(host);
    if (isDashboardOnlyHost) return TUNNEL_DEFAULT;
    return `${protocol}//${host}`;
  }
  return "http://localhost:8000";
}

export function setApiUrl(url: string) {
  if (typeof window === "undefined") return;
  const cleaned = url.trim().replace(/\/+$/, "");
  if (cleaned) window.localStorage.setItem(API_KEY, cleaned);
  else window.localStorage.removeItem(API_KEY);
}

export function clearApiUrl() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(API_KEY);
}

// Back-compat constant — UI code should call getApiUrl() at render time so
// it picks up changes after the user clicks "save & retry".
export const API_URL = (() => {
  if (BUILD_URL) return BUILD_URL.replace(/\/+$/, "");
  return "http://localhost:8000";
})();

async function j<T>(path: string, signal?: AbortSignal): Promise<T> {
  const base = getApiUrl();
  const r = await fetch(`${base}${path}`, {
    cache: "no-store",
    signal,
    // loca.lt warns the first time without this header
    headers: { "bypass-tunnel-reminder": "1" },
  });
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
  account: (m: Market, signal?: AbortSignal) =>
    m === "combined"
      ? j<Combined>("/combined/account", signal)
      : j<Account>(`${prefix(m)}/account`, signal),
  positions: (m: Market, signal?: AbortSignal) =>
    j<{ positions: Position[] }>(
      `${prefix(m === "combined" ? "crypto" : m)}/positions`,
      signal,
    ),
  positionsBoth: async (signal?: AbortSignal) => {
    const [c, s] = await Promise.all([
      j<{ positions: Position[] }>("/positions", signal),
      j<{ positions: Position[] }>("/stocks/positions", signal).catch(() => ({ positions: [] })),
    ]);
    return { crypto: c.positions, stocks: s.positions };
  },
  history: (m: Market, limit = 50, signal?: AbortSignal) =>
    j<{ trades: Trade[] }>(
      `${prefix(m === "combined" ? "crypto" : m)}/history?limit=${limit}`,
      signal,
    ),
  historyBoth: async (limit = 50, signal?: AbortSignal) => {
    const [c, s] = await Promise.all([
      j<{ trades: Trade[] }>(`/history?limit=${limit}`, signal),
      j<{ trades: Trade[] }>(`/stocks/history?limit=${limit}`, signal).catch(() => ({ trades: [] })),
    ]);
    const tag = (rows: Trade[], market: "crypto" | "stocks") =>
      rows.map((t) => ({ ...t, market }));
    return {
      trades: [...tag(c.trades, "crypto"), ...tag(s.trades, "stocks")]
        .sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""))
        .slice(0, limit),
    };
  },
  decisions: (m: Market, limit = 20, signal?: AbortSignal) =>
    j<{ decisions: Decision[] }>(
      `${prefix(m === "combined" ? "crypto" : m)}/decisions?limit=${limit}`,
      signal,
    ),
  decisionsBoth: async (limit = 20, signal?: AbortSignal) => {
    const [c, s] = await Promise.all([
      j<{ decisions: Decision[] }>(`/decisions?limit=${limit}`, signal),
      j<{ decisions: Decision[] }>(`/stocks/decisions?limit=${limit}`, signal).catch(() => ({
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
  health: (signal?: AbortSignal) => j<{ ok: boolean; stocks_db?: boolean }>("/health", signal),
};

// Probe a candidate base URL — used by the "fix it" dialog.
export async function probeApi(
  baseUrl: string,
  timeoutMs = 4000,
): Promise<{ ok: boolean; message: string }> {
  const cleaned = baseUrl.trim().replace(/\/+$/, "");
  if (!cleaned) return { ok: false, message: "empty url" };
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${cleaned}/health`, {
      cache: "no-store",
      signal: ctrl.signal,
      headers: { "bypass-tunnel-reminder": "1" },
    });
    if (!r.ok) return { ok: false, message: `health ${r.status}` };
    const j = (await r.json().catch(() => ({}))) as { ok?: boolean };
    if (j.ok === false) return { ok: false, message: "health reported not ok" };
    return { ok: true, message: "ok" };
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "fetch failed";
    return { ok: false, message: msg };
  } finally {
    clearTimeout(timer);
  }
}
