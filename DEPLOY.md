# Deployment — Oracle Cloud Free Tier + Vercel

## 0. One-time: create Oracle Cloud account + VM

1. Go to https://signup.cloud.oracle.com/. Fill in details. Credit card is requested for identity verification — **you will not be charged** for Always Free resources.
2. Pick the closest "Home Region":
   - `Mumbai` (ap-mumbai-1) or `Hyderabad` (ap-hyderabad-1) if you're in India.
   - Cannot be changed later.
3. Verify email + phone. Wait for approval (usually minutes, sometimes an hour).
4. Once inside the console:
   - Menu → Compute → **Instances** → Create instance.
   - Name: `jarvis`.
   - Image: **Ubuntu 22.04**.
   - Shape: **Ampere A1 Flex** (Always Free): **4 OCPU, 24 GB RAM**. (If out of capacity, try the smaller Always Free x86 VM or switch region.)
   - Networking: default VCN works.
   - Add SSH keys: paste your **public** key (generate with `ssh-keygen -t ed25519` locally if needed). Save the private key.
   - Create.
5. Wait for the instance to go `Running`. Copy the **Public IP address**.

## 1. Open inbound port 8000 (twice — both layers matter)

Oracle has **two** firewall layers; you must open both.

### Layer A: Oracle Security List

Console → Networking → Virtual Cloud Networks → your VCN → **Security Lists** → Default Security List → **Ingress Rules** → **Add**:
- Source CIDR: `0.0.0.0/0`
- IP Protocol: `TCP`
- Destination Port: `8000`
- Save.

### Layer B: host firewall (handled by `deploy.sh`)

`deploy.sh` runs `ufw allow 8000/tcp` automatically. Nothing to do manually.

## 2. SSH in and clone the repo

From your local machine:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<YOUR_VM_IP>
```

On the VM:

```bash
git clone https://github.com/<YOU>/hyperliquid-agent-jarvis
cd hyperliquid-agent-jarvis
cp .env.example .env
nano .env     # fill in GEMINI_API_KEY; keep PAPER_TRADING_MODE=true
```

## 3. Run deploy.sh

```bash
bash deploy.sh
```

What it does:
- Installs Python 3.12, Poetry, git, build tools.
- `poetry install` in the project dir.
- Writes `/etc/systemd/system/hyperliquid-agent.service`.
- Opens port 8000 on the host firewall.
- Starts the service (auto-restart on crash, auto-start on reboot).

Verify:

```bash
sudo systemctl status hyperliquid-agent.service
journalctl -u hyperliquid-agent.service -f        # live tail
curl http://localhost:8000/health                  # -> {"ok": true}
curl http://<YOUR_VM_IP>:8000/health               # from your laptop
```

## 4. (Recommended) Enable HTTPS with Caddy

Vercel serves the dashboard over HTTPS. If the backend is plain HTTP, browsers block the requests (mixed-content). Two options:

### Option A — Caddy (fully automatic HTTPS, ~5 min)

Prereq: point a domain at the VM IP (Cloudflare/Namecheap DNS → A record → IP).

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo tee /etc/caddy/Caddyfile <<'EOF'
jarvis.yourdomain.com {
    reverse_proxy localhost:8000
}
EOF
sudo systemctl restart caddy
```

Open ports 80 and 443 in the Oracle Security List. Caddy auto-provisions a Let's Encrypt cert. Your API is now at `https://jarvis.yourdomain.com`.

### Option B — Cloudflare Tunnel (no domain needed)

If you don't want to buy a domain:

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cf.deb
sudo dpkg -i cf.deb
cloudflared tunnel login            # opens a URL — auth via browser on your laptop
cloudflared tunnel create jarvis
cloudflared tunnel route dns jarvis jarvis-<random>.trycloudflare.com   # or your own domain
echo "url: http://localhost:8000" | sudo tee /etc/cloudflared/config.yml
sudo cloudflared service install
```

You get a free `*.trycloudflare.com` HTTPS URL. No ports to open.

## 5. Deploy the dashboard to Vercel

1. `cd dashboard && git init && git add -A && git commit -m "init"`
2. Push to a **new** GitHub repo (e.g. `jarvis-dashboard`):
   ```bash
   gh repo create jarvis-dashboard --public --source=. --push
   ```
3. https://vercel.com → Add New → Project → Import the repo.
4. Framework: Next.js (auto-detected).
5. Environment variables:
   - `NEXT_PUBLIC_API_URL` = `https://jarvis.yourdomain.com`  *(or your Cloudflare Tunnel URL)*
6. Deploy. First build takes ~2 min.

## 6. Monthly cost check

- Oracle Always Free: $0 as long as instance stays under 4 OCPU / 24 GB / 200 GB block storage.
- Vercel Hobby: $0 for personal projects.
- Gemini Free Tier: 10 req/min, 250 req/day — fine for 1h interval (~24 calls/day).
- Cloudflare Tunnel: free.
- Domain (if Option A): ~$10/yr if you buy one. Skip by choosing Option B.

Total: **₹0/month** with Option B.
