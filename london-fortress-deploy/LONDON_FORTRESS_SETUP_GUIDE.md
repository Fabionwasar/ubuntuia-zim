# London Fortress — Complete Setup and Deployment Guide

**Strategy:** London Fortress (GBP/USD Specialist)
**Author:** Manus AI
**Date:** February 20, 2026

---

## 1. System Overview

The London Fortress is a complete automated trading system for **GBP/USD** consisting of two components:

| Component | File | Purpose |
|-----------|------|---------|
| **Pine Script Strategy** | `London_Fortress_Strategy.pine` | TradingView indicator with visual signals, dashboard, and webhook alerts |
| **OANDA Trading Bot** | `london_fortress_oanda_bot.py` | Python bot that executes trades on your OANDA live account |

### How They Work Together

```
TradingView (Pine Script)
    ↓ Webhook Alert (JSON)
OANDA Bot (Flask Server)
    ↓ REST API
OANDA Live Account
    → 5x 0.01 lot trades executed
    → Progressive SL management
    → End-of-day close
```

---

## 2. Strategy Rules Summary

### Entry Conditions (ALL must be true)

| Timeframe | Condition | Purpose |
|-----------|-----------|---------|
| **Daily** | Price above/below 50 EMA | Institutional trend direction |
| **H4** | Supertrend bullish/bearish | Trend confirmation |
| **H4** | ADX > 20 | Trend strength (avoid choppy markets) |
| **H1** | Entry trigger fires | Specific entry signal |

### Entry Triggers (Priority Order)

| Priority | Trigger | Strength | Stacks |
|----------|---------|----------|--------|
| 1 | **London Breakout** — Price breaks Asian session range | STRONG (3/3) | 5 trades |
| 2 | **Supertrend Flip** — H4 ST direction change | STRONG (3/3) | 5 trades |
| 3 | **RSI Pullback** — RSI dips into buy/sell zone then reverses | MODERATE (2/3) | 5 trades |
| 4 | **EMA Cross** — 9 EMA crosses 21 EMA | MODERATE (2/3) | 5 trades |
| 5 | **Trend Continuation** — All aligned at session open | LIGHT (1/3) | 3 trades |

### Progressive Stop Loss Protection

| Stage | Trigger | New SL Position |
|-------|---------|-----------------|
| **0 → 1** | Price moves +10 pips in profit | Entry + 10 pips (breakeven protection) |
| **1 → 2** | Price reaches 25% of TP distance | 25% of the way to TP |
| **2 → 3** | Price reaches 50% of TP distance | 50% of the way to TP |
| **3 → 4** | Price reaches 75% of TP distance | 75% of the way to TP |

### Risk Management

- **Risk/Reward:** 1:2.5
- **Position Size:** 5x 100 units (0.01 lot each) = 500 units total per signal
- **Max Spread:** 3 pips (trades rejected if spread exceeds this)
- **Trading Hours:** 8:00 AM — 8:00 PM UK time (UTC)
- **End of Day:** All positions closed at 8:00 PM UK

---

## 3. TradingView Setup

### Step 1: Add the Pine Script

1. Open TradingView and navigate to **GBP/USD** on the **1H** timeframe
2. Click **Pine Editor** at the bottom of the screen
3. Delete any existing code
4. Copy and paste the entire contents of `London_Fortress_Strategy.pine`
5. Click **Add to Chart**
6. The strategy will appear with:
   - Gold line = Daily 50 EMA
   - Green/Red Supertrend lines with cloud
   - Blue/Orange EMA cloud (9/21)
   - Cyan Asian session range box
   - Buy/Sell labels with signal type and strength
   - Information dashboard (top-right corner)

### Step 2: Configure Strategy Settings

Click the **gear icon** on the strategy to adjust settings:

- **Higher Timeframe Filters:** Leave defaults (Daily 50 EMA, H4 ST 20/3.5, ADX 14/20)
- **Entry Settings:** Leave defaults (9/21 EMA, RSI 14, Buy<40, Sell>60)
- **London Breakout:** Asian 0-8 UTC, 5 pip buffer
- **Session Filter:** 8-20 UTC
- **Risk Management:** R:R 2.5, 5 stacks, breakeven 10 pips, all trail levels ON
- **Properties tab:** Set initial capital to 95, commission to 0

### Step 3: Set Up Webhook Alerts

1. Click **Alerts** (bell icon) in TradingView
2. Create alerts for each signal type:

**Alert 1: Strong Buy**
- Condition: `London Fortress [GBP/USD]` → `STRONG BUY Signal`
- Webhook URL: `http://YOUR_SERVER_IP:5000/webhook`
- Message: (auto-filled from Pine Script)

**Alert 2: Moderate Buy**
- Condition: `London Fortress [GBP/USD]` → `MODERATE BUY Signal`
- Same webhook URL

**Alert 3-6:** Repeat for Strong/Moderate Sell signals

**Alert 7: SL Stage Changes** (create one for each stage)
**Alert 8: EOD Close All**

> **Note:** TradingView webhook alerts require a **Pro** plan or higher.

---

## 4. OANDA Bot Setup

### Step 1: Install Dependencies

```bash
pip3 install flask requests schedule
```

### Step 2: Configure the Bot

The bot is pre-configured with your credentials:
- API Key: `08c10311...e96153`
- Account: `001-004-20593634-003`
- Environment: `live`

To change settings, edit the configuration section at the top of `london_fortress_oanda_bot.py`.

### Step 3: Run the Bot

```bash
# Run directly
python3 london_fortress_oanda_bot.py

# Or run in background with nohup
nohup python3 london_fortress_oanda_bot.py > /dev/null 2>&1 &

# Or use screen for persistent sessions
screen -S fortress
python3 london_fortress_oanda_bot.py
# Press Ctrl+A then D to detach
# screen -r fortress to reattach
```

### Step 4: Verify Connection

```bash
# Check health
curl http://localhost:5000/health

# Check detailed status
curl http://localhost:5000/status

# Trigger manual scan
curl -X POST http://localhost:5000/scan

# Close all positions
curl -X POST http://localhost:5000/close_all
```

---

## 5. Bot Operation Modes

### Mode 1: Standalone (Self-Scanning)

The bot runs its own market analysis on a schedule:

| Event | Time (UTC) | Action |
|-------|-----------|--------|
| London Open | 08:00 | Full market scan + Asian range lock |
| Hourly Scan | Every hour | Check for new signals |
| US Open | 13:00 | Full market scan |
| SL Check | Every 5 min | Progressive SL management |
| End of Day | 20:00 | Close all + daily report |

### Mode 2: Webhook Receiver (TradingView Signals)

The bot receives signals from TradingView webhooks and executes them:

**Webhook URL:** `http://YOUR_SERVER_IP:5000/webhook`

**Example webhook payloads:**

```json
// Buy signal
{"action":"BUY","pair":"GBP_USD","strength":3,"type":"BREAKOUT","sl":1.26200,"tp":1.27250,"stack":5}

// Modify SL
{"action":"MODIFY_SL","pair":"GBP_USD","stage":"breakeven","new_sl":1.26350}

// Close all
{"action":"CLOSE_ALL","pair":"GBP_USD","reason":"end_of_day"}
```

### Mode 3: Hybrid (Recommended)

Run both modes simultaneously. The bot scans independently AND accepts TradingView webhooks. This provides redundancy — if one signal source misses an entry, the other catches it.

---

## 6. Monitoring

### Log File
```bash
tail -f /home/ubuntu/london_fortress.log
```

### Daily Reports
Reports are saved to `/home/ubuntu/trading_reports/` as Markdown files:
```bash
cat /home/ubuntu/trading_reports/london_fortress_2026-02-20.md
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Quick health check |
| `/status` | GET | Detailed status with trade info |
| `/scan` | POST | Trigger manual market scan |
| `/close_all` | POST | Emergency close all positions |
| `/webhook` | POST | Receive TradingView signals |

---

## 7. Dashboard Indicators (Pine Script)

The information dashboard on TradingView shows:

| Field | Description |
|-------|-------------|
| Daily Trend | Bullish/Bearish based on 50 EMA |
| H4 Supertrend | Current H4 ST direction |
| H4 ADX | Trend strength value |
| H1 EMA Cross | 9/21 EMA alignment |
| H1 RSI | Current RSI value and zone |
| Session | London / London+US / Closed |
| Asian Range | Today's breakout levels |
| Open Trades | Current stack count |
| SL Stage | Current progressive SL level |
| Signal | Current signal and strength |
| Net P/L | Strategy backtest P/L |

---

## 8. Important Notes

1. **This is a LIVE trading system.** Real money is at risk. Monitor closely for the first week.
2. **Maximum risk per trade:** 5x 100 units = 500 units of GBP/USD. At current prices, this is approximately £3-5 risk per signal (depending on SL distance).
3. **The progressive SL system** is designed to protect profits aggressively. Once a trade moves 10 pips in profit, you can never lose on that trade.
4. **Weekend gaps:** The bot does not trade on weekends. All positions should be closed by 8PM Friday.
5. **Spread filter:** The bot will not enter trades when the spread exceeds 3 pips, protecting against low-liquidity periods.

---

## 9. File Inventory

| File | Description |
|------|-------------|
| `London_Fortress_Strategy.pine` | TradingView Pine Script v5 strategy |
| `london_fortress_oanda_bot.py` | Python OANDA trading bot |
| `gbpusd_strategy_recommendation.md` | Strategy research and rationale |
| `LONDON_FORTRESS_SETUP_GUIDE.md` | This setup guide |
| `Supertrend_EMA_Scalper.pine` | Original scalper indicator (reference) |
| `supertrend_ema_oanda_bot.py` | Original bot (superseded) |
