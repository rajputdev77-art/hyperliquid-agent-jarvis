# Hosting — pick one (Oracle charged you twice, here are alternatives)

Oracle Cloud Always-Free is fine when it works, but their signup flow charges a ₹50 auth that sometimes fails and *also* books the charge. If you're hitting "contact support" errors, skip Oracle. Pick the option below that fits.

| Option | Cost | Setup time | Best for |
|---|---|---|---|
| **A. Run on your own Windows PC** | ₹0 | 5 min | Just trying it out. PC must stay on. |
| **B. Fly.io** | ₹0 (free tier: 3 shared-CPU VMs) | 15 min | Proper 24/7 cloud, no credit card. |
| **C. Render** | ₹0 (free web service, 750 hr/mo) | 10 min | Zero-config Docker. |
| **D. Railway** | $5 trial credit | 10 min | Easiest UI. Will eventually cost money. |
| **E. GitHub Codespaces** | ₹0 (120 hr/mo free) | 3 min | Don't want to install anything. |
| **F. Retry Oracle** | ₹0 | 20 min | Willing to fight again. |

Pick one and follow the section below. **Option A is what I'd do if this is new** — it's already working on your laptop right now.

---

## A. Run on your own Windows PC

Your bot is already running. Make it auto-start on boot.

1. Press **Win + R**, type `shell:startup`, press Enter. A folder opens.
2. Right-click inside → **New** → **Text Document**. Name it `jarvis.bat`. Click **Yes** when Windows asks if you want to change the extension.
3. Right-click `jarvis.bat` → **Edit** (or Open with Notepad).
4. Paste this, exactly:
   ```
   cd /d C:\Users\Dev\Desktop\Trading
   .venv\Scripts\python.exe -m src.main
   ```
5. Save, close. Done — next time you log into Windows, the bot starts.

To see it running: open PowerShell and run `curl http://localhost:8000/health`. You should see `{"ok":true}`.

To make the dashboard reachable from the internet (so Vercel can hit it), use a **Cloudflare Tunnel** — free, no port-forwarding:

1. Go to https://one.dash.cloudflare.com/ → sign up free.
2. Left sidebar: **Networks** → **Tunnels** → **Create a tunnel**.
3. Pick **Cloudflared**. Name it `jarvis`. Click Save.
4. Cloudflare shows you a command like `cloudflared.exe service install eyJhIjoi...`. Copy it.
5. Download cloudflared from https://github.com/cloudflare/cloudflared/releases/latest → pick `cloudflared-windows-amd64.exe` → rename to `cloudflared.exe`.
6. Open PowerShell **as Administrator**, `cd` to where you saved it, paste the command from step 4.
7. Back in the Cloudflare dashboard: **Public Hostname** → **Add a public hostname**.
   - Subdomain: `jarvis`
   - Domain: whichever domain you have (or use a free `trycloudflare.com` subdomain)
   - Service type: `HTTP`
   - URL: `localhost:8000`
8. Save. Your API is now at `https://jarvis.yourdomain.com`.

---

## B. Fly.io (recommended cloud option, ₹0)

No credit card for the free tier. Keeps running 24/7 even when your PC is off.

1. Go to https://fly.io/app/sign-up → sign up with GitHub.
2. Install the Fly CLI: open PowerShell and paste:
   ```
   iwr https://fly.io/install.ps1 -useb | iex
   ```
3. Restart PowerShell. Run `fly auth login` — a browser opens, log in.
4. In the Trading folder, create a file called `Dockerfile` (no extension) — I'll give you the contents below.
5. Run `fly launch --no-deploy`. Accept defaults, pick region `bom` (Mumbai) or `sin` (Singapore).
6. Set your secrets (Gemini key etc):
   ```
   fly secrets set GEMINI_API_KEY=YOUR_GEMINI_KEY_HERE PAPER_TRADING_MODE=true ASSETS="BTC ETH SOL" INTERVAL=1h
   ```
7. Deploy: `fly deploy`. First build takes ~5 min.
8. URL: `fly status` shows the hostname (something like `jarvis.fly.dev`).

**Dockerfile** — paste into `C:\Users\Dev\Desktop\Trading\Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir hyperliquid-python-sdk google-genai python-dotenv aiohttp pandas numpy fastapi "uvicorn[standard]" requests
COPY src ./src
EXPOSE 8000
CMD ["python", "-m", "src.main"]
```

---

## C. Render (simplest Docker host, ₹0)

1. Go to https://render.com/ → sign up with GitHub (no card).
2. Top bar → **New +** → **Web Service**.
3. Pick `rajputdev77-art/hyperliquid-agent-jarvis`.
4. Fill in:
   - **Runtime**: Docker
   - **Plan**: Free
   - **Region**: Singapore
5. Add the Dockerfile from Option B (commit + push it to the repo first).
6. **Environment** tab → add these vars:
   - `GEMINI_API_KEY` = your key
   - `PAPER_TRADING_MODE` = `true`
   - `ASSETS` = `BTC ETH SOL`
   - `INTERVAL` = `1h`
7. Click **Create Web Service**. Wait ~3 min. URL is shown at the top.

⚠️ Render's free tier sleeps after 15 min of inactivity. Since the bot runs every 1h, it will wake up by itself each cycle, but the dashboard may take 30s to respond when you open it.

---

## D. Railway ($5 trial)

1. https://railway.com/ → sign up with GitHub.
2. **New project** → **Deploy from GitHub repo** → pick `hyperliquid-agent-jarvis`.
3. Settings → **Variables** → add the same 4 env vars as Render.
4. Settings → **Networking** → **Generate Domain**.
5. Done. URL appears immediately.

You get $5 free to test. After that it's ~$5/mo.

---

## E. GitHub Codespaces (₹0, 120 hr/mo)

Fastest way to try it on cloud without installing anything.

1. Go to https://github.com/rajputdev77-art/hyperliquid-agent-jarvis
2. Green **Code** button → **Codespaces** tab → **Create codespace on master**.
3. Wait ~1 min. A VS Code in your browser opens.
4. In its terminal, paste:
   ```
   pip install hyperliquid-python-sdk google-genai python-dotenv aiohttp pandas numpy fastapi "uvicorn[standard]" requests
   cp .env.example .env
   ```
5. Open `.env` in the editor. Paste your Gemini key next to `GEMINI_API_KEY=`. Save.
6. In the terminal: `python -m src.main`.
7. When port `8000` opens, Codespaces shows a popup — click **Make Public** if you want to reach it from Vercel.

Limit: 120 hours/month on free tier. Enough for ~5 hours/day.

---

## F. Retry Oracle — if you want your ₹50×2 back

Oracle charges are refunded automatically within 7–14 days when auth fails. Check with your bank. If you want to try again:

1. Use a **different browser** (their signup hates cached cookies). Firefox Private Window works best.
2. Use a **different card** or a virtual UPI card (e.g. OneCard or HDFC PayZapp virtual card).
3. Pick **Mumbai** or **Hyderabad** region (Singapore fails more often from Indian IPs).
4. If "contact support" error appears: wait 24 h and try again. It's usually a soft rate-limit on their side.
5. Follow the rest of `DEPLOY.md` once inside the Oracle Console.

Honestly: if A or B works, skip Oracle. The ₹0 guarantee is real but the signup friction is not worth it.

---

## Deploying the dashboard to Vercel (applies to ALL options above)

1. Go to https://vercel.com/signup → sign in with GitHub.
2. **Add New** → **Project** → pick `rajputdev77-art/jarvis-dashboard`.
3. Framework preset: **Next.js** (auto-detected).
4. **Environment Variables** → add one:
   - Key: `NEXT_PUBLIC_API_URL`
   - Value: the URL of your backend from whichever option above (e.g. `https://jarvis.fly.dev` or `https://jarvis.yourdomain.com`)
5. Click **Deploy**. Wait ~90 s. Your dashboard is at `jarvis-dashboard-xxxx.vercel.app`.

If the dashboard shows CORS errors in the browser console, it means the backend URL isn't reachable. Open that URL directly in a new tab — if it returns `{"ok":true}` at `/health`, the backend is fine. Otherwise, revisit the hosting option above.
