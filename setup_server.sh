#!/usr/bin/env bash
set -e

echo "========================================="
echo "   BlackFoxBot VPS Deployment Script    "
echo "========================================="

# 1. Update and install prerequisites
echo "[1/5] Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y && apt-get upgrade -y
apt-get install -y python3 python3-pip python3-venv git curl wget htop ufw ffmpeg

# 2. Setup project directory
PROJECT_DIR="/root/BlackFoxBot"
echo "[2/5] Setting up project directory at $PROJECT_DIR..."
mkdir -p "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/logs"

# 3. Setup Python Virtual Environment
echo "[3/5] Setting up Python virtual environment..."
cd "$PROJECT_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel

# 4. Install dependencies
if [ -f "requirements.txt" ]; then
    echo "[4/5] Installing Python dependencies..."
    pip install -r requirements.txt
else
    echo "[4/5] Installing core dependencies..."
    pip install aiogram aiohttp telethon pyrogram python-dotenv pydantic
fi

# 5. Create Systemd Service for Worker Bot
echo "[5/5] Creating systemd service units..."

cat << 'EOF' > /etc/systemd/system/blackfox-worker.service
[Unit]
Description=BlackFoxBot Worker Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlackFoxBot
EnvironmentFile=/root/BlackFoxBot/.env
ExecStart=/root/BlackFoxBot/.venv/bin/python -m worker_bot.main --token 8991697233:AAFilQj32pmW7fA2SYbbJbbqRcTzUFroC5U
Restart=always
RestartSec=5
StandardOutput=null
StandardError=null

[Install]
WantedBy=multi-user.target
EOF

# Create Systemd Service for Admin Bot
cat << 'EOF' > /etc/systemd/system/blackfox-admin.service
[Unit]
Description=BlackFoxBot Admin Orchestrator Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlackFoxBot
EnvironmentFile=/root/BlackFoxBot/.env
ExecStart=/root/BlackFoxBot/.venv/bin/python -m admin_bot.main
Restart=always
RestartSec=5
StandardOutput=append:/root/BlackFoxBot/logs/admin.log
StandardError=append:/root/BlackFoxBot/logs/admin_err.log

[Install]
WantedBy=multi-user.target
EOF

# Reload and enable services
systemctl daemon-reload
systemctl stop blackfox-worker || true
systemctl disable blackfox-worker || true
systemctl enable blackfox-admin
systemctl restart blackfox-admin

echo "========================================="
echo "   Deployment Setup Completed!          "
echo "========================================="
echo "To start services:"
echo "  systemctl start blackfox-admin"
echo ""
echo "To check status:"
echo "  systemctl status blackfox-admin"
echo ""
echo "To view logs:"
echo "  tail -f /root/BlackFoxBot/logs/admin.log"
