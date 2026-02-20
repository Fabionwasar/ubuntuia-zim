# London Fortress — DigitalOcean Deployment Guide

## What You're Setting Up

A small cloud server ($4/month) that runs your London Fortress trading bot 24/7. The bot will:
- Scan GBP/USD every hour during London session (8AM–8PM UTC)
- Place up to 5 stacked trades (0.01 lots each) when signals align
- Manage stop losses progressively (breakeven → 25% → 50% → 75% toward TP)
- Close all positions at end of day
- Auto-restart if it crashes or the server reboots

---

## Step 1: Create a DigitalOcean Account

1. Go to **https://www.digitalocean.com**
2. Click **"Sign Up"**
3. You can sign up with your email or Google/GitHub account
4. You'll need to add a payment method (credit/debit card or PayPal)
5. DigitalOcean often gives **$200 free credit for 60 days** to new users

---

## Step 2: Create a Droplet (Your Server)

1. Once logged in, click **"Create"** → **"Droplets"**
2. Choose these settings:

| Setting | Value |
|---|---|
| **Region** | London (LON1) — closest to OANDA servers |
| **Image** | Ubuntu 22.04 (LTS) x64 |
| **Size** | Basic → Regular → **$4/mo** (512 MB RAM, 1 vCPU) |
| **Authentication** | Choose **Password** (easier) — set a strong root password |
| **Hostname** | `london-fortress` |

3. Click **"Create Droplet"**
4. Wait ~60 seconds for it to spin up
5. Copy the **IP address** shown (e.g., `164.92.xxx.xxx`)

---

## Step 3: Connect to Your Server

### On Mac (Terminal):
```bash
ssh root@YOUR_IP_ADDRESS
```
Type `yes` when asked about fingerprint, then enter your password.

### On Windows (PowerShell):
```bash
ssh root@YOUR_IP_ADDRESS
```
Or download PuTTY from https://putty.org

---

## Step 4: Upload the Bot Files

### Option A: Using SCP (Recommended)
Open a **new terminal window** on your Mac (keep the SSH one open) and run:

```bash
scp -r /path/to/deploy/* root@YOUR_IP_ADDRESS:/root/
```

Replace `/path/to/deploy/` with wherever you saved the deploy folder.

### Option B: Using GitHub
If the files are on your GitHub repo:
```bash
# On the server (via SSH):
apt-get install -y git
git clone https://github.com/Fabionwasar/ubuntuia-zim.git
cp ubuntuia-zim/deploy/* /root/
```

### Option C: Copy-Paste Method
If the above don't work, you can copy the bot file contents directly:
```bash
# On the server (via SSH):
nano /root/london_fortress_oanda_bot.py
# Paste the entire bot code, then press Ctrl+X, Y, Enter to save

nano /root/requirements.txt
# Paste: requests>=2.28.0
#        flask>=2.3.0
#        schedule>=1.2.0
# Save with Ctrl+X, Y, Enter

nano /root/setup.sh
# Paste the setup script contents, save with Ctrl+X, Y, Enter
```

---

## Step 5: Run the Setup Script

```bash
chmod +x /root/setup.sh
bash /root/setup.sh
```

This will:
- Install Python and all dependencies
- Set up the bot as a system service (auto-starts on boot)
- Configure the firewall
- Start the bot immediately

You should see:
```
╔════════════════════════════════════════════════════════════╗
║  DEPLOYMENT COMPLETE!                                      ║
╚════════════════════════════════════════════════════════════╝
```

---

## Step 6: Verify It's Working

```bash
# Check bot status
systemctl status london-fortress

# Watch live logs
journalctl -u london-fortress -f

# Check the log file
tail -50 /opt/london-fortress/logs/bot.log
```

You should see the bot scanning GBP/USD and reporting market conditions.

---

## Step 7: Set Up TradingView Webhook (Optional)

If you have TradingView Premium, you can send alerts directly to the bot:

1. On TradingView, open your GBP/USD 1H chart with London Fortress
2. Click **"Alert"** in the top toolbar
3. Set **Condition** → "London Fortress" → choose an alert (e.g., "STRONG BUY Signal")
4. Check **"Webhook URL"** and enter: `http://YOUR_IP_ADDRESS:5000/webhook`
5. Click **"Create"**

The bot will execute trades instantly when TradingView sends an alert.

**Note:** The bot works perfectly WITHOUT webhooks too — it scans OANDA directly every hour.

---

## Daily Management Commands

| Command | What It Does |
|---|---|
| `journalctl -u london-fortress -f` | Watch live bot activity |
| `systemctl restart london-fortress` | Restart the bot |
| `systemctl stop london-fortress` | Stop the bot (no more trades) |
| `systemctl start london-fortress` | Start the bot again |
| `systemctl status london-fortress` | Check if bot is running |
| `tail -100 /opt/london-fortress/logs/bot.log` | View recent log entries |
| `cat /opt/london-fortress/logs/bot_error.log` | Check for errors |

---

## Troubleshooting

**Bot not starting?**
```bash
journalctl -u london-fortress --no-pager | tail -30
```

**Need to update the bot code?**
```bash
nano /opt/london-fortress/london_fortress_oanda_bot.py
# Make changes, save, then:
systemctl restart london-fortress
```

**Want to check your OANDA account from the server?**
```bash
curl -s -H "Authorization: Bearer 08c10311c9d6136650e48bc25eb5980f-a295f483296c61be40ce577472e96153" \
  https://api-fxtrade.oanda.com/v3/accounts/001-004-20593634-003/summary | python3 -m json.tool
```

---

## Monthly Cost

| Item | Cost |
|---|---|
| DigitalOcean Droplet | $4/month |
| OANDA Account | Free |
| TradingView (Basic) | Free |
| **Total** | **$4/month** |

---

## Security Notes

- Your OANDA API key is stored in the bot file on the server
- The server firewall only allows SSH (port 22) and webhook (port 5000)
- Consider changing the SSH port and disabling password auth after setup for extra security
- Never share your server IP or API keys publicly
