#!/usr/bin/env bash
# deploy.sh — idempotent Oracle Cloud (Ubuntu 22.04, ARM or x86) setup.
#
# Run AS THE `ubuntu` USER on the VM:
#     curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy.sh | bash
# or, from the repo root after a `git clone`:
#     bash deploy.sh
#
# Idempotent: re-run to upgrade or repair.

set -euo pipefail

APP_USER="${SUDO_USER:-${USER:-ubuntu}}"
APP_HOME="/home/${APP_USER}"
APP_DIR="${APP_HOME}/hyperliquid-agent-jarvis"
PY=python3.12
SERVICE_NAME=hyperliquid-agent.service

say() { printf "\033[1;36m[deploy]\033[0m %s\n" "$*"; }
die() { printf "\033[1;31m[deploy:error]\033[0m %s\n" "$*" >&2; exit 1; }

# --- 1. Packages ---
say "apt update + base packages"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  software-properties-common curl git build-essential pkg-config \
  libffi-dev libssl-dev

# Python 3.12 via deadsnakes (works on Ubuntu 22.04 for both amd64 and arm64)
if ! command -v ${PY} >/dev/null; then
  say "installing Python 3.12"
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -y
  sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
fi

# --- 2. Poetry ---
if ! command -v poetry >/dev/null; then
  say "installing Poetry"
  curl -sSL https://install.python-poetry.org | ${PY} -
  # add to PATH for this shell and future logins
  grep -q 'poetry/bin' "${APP_HOME}/.profile" 2>/dev/null || \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${APP_HOME}/.profile"
  export PATH="${APP_HOME}/.local/bin:${PATH}"
fi

# --- 3. Project checkout ---
if [ ! -d "${APP_DIR}/.git" ]; then
  die "Expected repo at ${APP_DIR}. Clone it first: git clone <url> ${APP_DIR}"
fi
cd "${APP_DIR}"

say "installing project deps (may take 2-3 min first time)"
poetry env use ${PY} >/dev/null
poetry install --no-interaction --no-root

mkdir -p data logs data/llm_logs

# --- 4. .env sanity ---
if [ ! -f "${APP_DIR}/.env" ]; then
  say "copying .env.example -> .env (YOU must fill in GEMINI_API_KEY)"
  cp .env.example .env
fi

# --- 5. systemd unit ---
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"
say "writing ${UNIT_PATH}"
POETRY_BIN="$(command -v poetry)"
sudo tee "${UNIT_PATH}" >/dev/null <<EOF
[Unit]
Description=hyperliquid-agent-jarvis (paper trading)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${POETRY_BIN} run python -m src.main
Restart=on-failure
RestartSec=5
StandardOutput=append:${APP_DIR}/logs/systemd.log
StandardError=append:${APP_DIR}/logs/systemd.err.log
# Tame resource usage on the Free Tier box:
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

# --- 6. Firewall (ufw + cloud security list reminder) ---
if command -v ufw >/dev/null; then
  say "ufw: opening port 8000 (internal) and 22"
  sudo ufw allow 22/tcp   || true
  sudo ufw allow 8000/tcp || true
  sudo ufw --force enable || true
fi
# Oracle's Linux images also use iptables rules shipped in /etc/iptables/rules.v4
if [ -f /etc/iptables/rules.v4 ]; then
  if ! sudo grep -q "dport 8000" /etc/iptables/rules.v4; then
    say "adding iptables ACCEPT for tcp 8000"
    sudo iptables -I INPUT 6 -p tcp --dport 8000 -j ACCEPT
    sudo netfilter-persistent save || sudo iptables-save | sudo tee /etc/iptables/rules.v4 >/dev/null
  fi
fi

say "IMPORTANT: also open port 8000 in the Oracle Cloud SECURITY LIST / NSG"
say "  Console → Networking → VCNs → <your VCN> → Security Lists → Default → Ingress Rules → Add"
say "  Source 0.0.0.0/0, TCP, Destination port 8000"

# --- 7. Start service ---
say "starting ${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sleep 2
sudo systemctl --no-pager status "${SERVICE_NAME}" || true

say "done. Tail logs:  journalctl -u ${SERVICE_NAME} -f"
say "                  tail -f ${APP_DIR}/logs/agent.log"
