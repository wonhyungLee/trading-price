#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wonyodd-reco"
PORT="8010"
USER_NAME="$(whoami)"

echo "[1/8] Create app dir: $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

echo "[2/8] Copy files"
rsync -a --delete backend/ "$APP_DIR/backend/"
rsync -a --delete frontend/ "$APP_DIR/frontend/"
if [ -d "frontend-react" ]; then
  rsync -a --delete frontend-react/ "$APP_DIR/frontend-react/"
fi
rsync -a README.md "$APP_DIR/README.md"

echo "[3/8] Create data dir"
mkdir -p "$APP_DIR/data"

echo "[4/8] Python venv + deps"
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/backend/requirements.txt"

echo "[5/8] Create .env if missing"
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
WONYODD_DIRECTION_ENGINE_ENABLED=false
EOF
fi

echo "[6/8] Systemd API service"
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

echo "[7/8] Systemd OKX sync (1m)"
DB_SYNC_SERVICE_PATH="/etc/systemd/system/wonyodd-db-sync.service"
sudo tee "$DB_SYNC_SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=Wonyodd DB Sync from OKX
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/.env
Environment=WONYODD_DB_PATH=$APP_DIR/data/wonyodd.sqlite3
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/backend/tools/sync_okx_db.py --db-path $APP_DIR/data/wonyodd.sqlite3 --inst-id BTC-USDT.P --sync-minutes 240 --day-sync-count 7 --timeout 10 --retries 2 --pause-sec 0.05 --summary-json $APP_DIR/data/db_sync_summary.json
User=$USER_NAME
StandardOutput=append:$APP_DIR/data/db_sync.log
StandardError=append:$APP_DIR/data/db_sync.log

[Install]
WantedBy=multi-user.target
EOF

DB_SYNC_TIMER_PATH="/etc/systemd/system/wonyodd-db-sync.timer"
sudo tee "$DB_SYNC_TIMER_PATH" >/dev/null <<EOF
[Unit]
Description=Run Wonyodd DB Sync every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Persistent=true
Unit=wonyodd-db-sync.service

[Install]
WantedBy=timers.target
EOF

echo "[8/8] Enable and restart services"
sudo systemctl daemon-reload
sudo systemctl enable wonyodd-reco
sudo systemctl restart wonyodd-reco
sudo systemctl enable wonyodd-db-sync.timer
sudo systemctl restart wonyodd-db-sync.timer
sudo systemctl start wonyodd-db-sync.service

echo "[Optional] Build React UI (if Node.js is available)"
if [ -d "$APP_DIR/frontend-react" ] && command -v npm >/dev/null 2>&1; then
  pushd "$APP_DIR/frontend-react" >/dev/null
  if [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
  npm run build
  rsync -a --delete dist/ "$APP_DIR/frontend/"
  popd >/dev/null
  echo "React build deployed to $APP_DIR/frontend (served by FastAPI)."
else
  echo "Node.js/npm not found (or frontend-react missing). Keeping static frontend/ as-is."
fi

echo "[done]"
echo "Open: http://<server-ip>:$PORT/"
echo "Webhook: POST http://<server-ip>:$PORT/api/webhook/tradingview"
echo "OKX Sync: systemctl status wonyodd-db-sync.timer"
