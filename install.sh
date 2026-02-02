#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wonyodd-reco"
PORT="8010"
USER_NAME="$(whoami)"

echo "[1/7] Create app dir: $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

echo "[2/7] Copy files"
rsync -a --delete backend/ "$APP_DIR/backend/"
rsync -a --delete frontend/ "$APP_DIR/frontend/"
rsync -a README.md "$APP_DIR/README.md"

echo "[3/7] Create data dir"
mkdir -p "$APP_DIR/data"

echo "[4/7] Python venv + deps"
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/backend/requirements.txt"

echo "[5/7] Create .env if missing"
if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<'EOF'
# Optional: set a shared secret (recommended)
WONYODD_WEBHOOK_SECRET=

# SQLite DB path
WONYODD_DB_PATH=/opt/wonyodd-reco/data/wonyodd.sqlite3

# Risk settings
WONYODD_RISK_PCT_DEFAULT=0.5
WONYODD_MAX_LEVERAGE=10.0

# ATR-based entry (tune later)
WONYODD_ENTRY_ATR_K_30=1.0
WONYODD_ENTRY_ATR_K_60=0.25
WONYODD_ENTRY_ATR_K_180=0.6
WONYODD_STOP_ATR_MULT=1.5
EOF
fi

echo "[6/7] Systemd service"
SERVICE_PATH="/etc/systemd/system/wonyodd-reco.service"
sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=Wonyodd Reco Engine (TradingView webhook -> UI)
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3
User=$USER_NAME

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable wonyodd-reco
sudo systemctl restart wonyodd-reco

echo "[7/7] Done"
echo "Open: http://<server-ip>:$PORT/"
echo "Webhook: POST http://<server-ip>:$PORT/api/webhook/tradingview"
