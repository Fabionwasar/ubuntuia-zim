#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  LONDON FORTRESS — DigitalOcean One-Click Deployment
#  Run this script on a fresh Ubuntu 22.04 droplet
# ═══════════════════════════════════════════════════════════════

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  LONDON FORTRESS BOT — DigitalOcean Setup                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Update system
echo "→ Updating system packages..."
apt-get update -y && apt-get upgrade -y

# Install Python and dependencies
echo "→ Installing Python 3 and pip..."
apt-get install -y python3 python3-pip python3-venv ufw

# Create bot directory
echo "→ Creating bot directory..."
mkdir -p /opt/london-fortress
cd /opt/london-fortress

# Copy bot file (assumes it's in the same directory as this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/london_fortress_oanda_bot.py" /opt/london-fortress/
cp "$SCRIPT_DIR/requirements.txt" /opt/london-fortress/

# Install Python dependencies
echo "→ Installing Python dependencies..."
pip3 install -r requirements.txt

# Create log directory
mkdir -p /opt/london-fortress/logs

# Set up systemd service for auto-start
echo "→ Setting up systemd service..."
cat > /etc/systemd/system/london-fortress.service << 'EOF'
[Unit]
Description=London Fortress GBP/USD Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/london-fortress
ExecStart=/usr/bin/python3 /opt/london-fortress/london_fortress_oanda_bot.py
Restart=always
RestartSec=30
StandardOutput=append:/opt/london-fortress/logs/bot.log
StandardError=append:/opt/london-fortress/logs/bot_error.log

# Environment variables (optional - bot has defaults hardcoded)
# Uncomment and edit these if you want to override the defaults:
# Environment=OANDA_API_KEY=your_api_key_here
# Environment=OANDA_ACCOUNT_ID=your_account_id_here

[Install]
WantedBy=multi-user.target
EOF

# Set up log rotation
echo "→ Setting up log rotation..."
cat > /etc/logrotate.d/london-fortress << 'EOF'
/opt/london-fortress/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl restart london-fortress
    endscript
}
EOF

# Configure firewall
echo "→ Configuring firewall..."
ufw allow 22/tcp    # SSH
ufw allow 5000/tcp  # Webhook receiver
ufw --force enable

# Enable and start the service
echo "→ Starting London Fortress bot..."
systemctl daemon-reload
systemctl enable london-fortress
systemctl start london-fortress

# Wait a moment and check status
sleep 5
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  DEPLOYMENT COMPLETE!                                      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Bot Status:"
systemctl status london-fortress --no-pager | head -15
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  USEFUL COMMANDS:"
echo "═══════════════════════════════════════════════════════════════"
echo "  View live logs:     journalctl -u london-fortress -f"
echo "  View bot log:       tail -f /opt/london-fortress/logs/bot.log"
echo "  Restart bot:        systemctl restart london-fortress"
echo "  Stop bot:           systemctl stop london-fortress"
echo "  Check status:       systemctl status london-fortress"
echo ""
echo "  Webhook URL:        http://$(curl -s ifconfig.me):5000/webhook"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Your bot is now running 24/7 and will auto-restart on reboot!"
echo ""
