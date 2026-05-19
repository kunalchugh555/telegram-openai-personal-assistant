#!/bin/bash
# Run this script on the Google Cloud VM after SSH-ing in.
# It installs all dependencies, clones the repo, and registers the bot
# as a systemd service that starts automatically on reboot.
#
# Usage (from your local machine):
#   gcloud compute ssh telegram-assistant --zone=us-central1-a -- 'bash -s' < scripts/setup_vm.sh

set -e

REPO_URL="https://github.com/kunalchugh555/telegram-openai-personal-assistant.git"
APP_DIR="$HOME/telegram-openai-personal-assistant"
SERVICE_NAME="telegram-assistant"

echo "=== Installing system dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv ffmpeg git

echo "=== Cloning repository ==="
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== Setting up Python virtualenv ==="
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "=== Registering systemd service ==="
sudo tee "/etc/systemd/system/$SERVICE_NAME.service" > /dev/null <<EOF
[Unit]
Description=Telegram Personal Assistant Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Now copy your secrets from your local machine (run these locally):"
echo "  gcloud compute scp .env telegram-assistant:$APP_DIR/.env --zone=us-central1-a --project=personal-assistant-kunal"
echo "  gcloud compute scp token.json telegram-assistant:$APP_DIR/token.json --zone=us-central1-a --project=personal-assistant-kunal"
echo ""
echo "Then start the bot:"
echo "  sudo systemctl start $SERVICE_NAME"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  sudo journalctl -u $SERVICE_NAME -f"
