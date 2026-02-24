"""
Mean-Reversion Trading Bot — RSI + Bollinger Bands
===================================================
Strategy: Counter-trend mean-reversion with layered filtering
Timeframe: M15 (15-minute candles)
Pairs: EUR/USD, GBP/USD, USD/JPY
Broker: OANDA REST v20 API (DEMO for validation)

Features:
- RSI oversold/overbought detection (RSI < 30 = Buy, RSI > 70 = Sell)
- Bollinger Band extremes (price at upper/lower band)
- Session filtering (London/NY overlap 1-4 PM UTC)
- Dynamic position sizing based on ATR volatility
- Multi-pair trading with max 1 position per pair
- Trailing stop to breakeven at 50% profit
- Daily loss limit protection (3% max drawdown)
- Telegram notifications for all trade events

Author: Manus AI — Mean-Reversion System
"""

import os
import json
import math
import time
import requests
import schedule
import logging
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from telegram_notifier import (
    notify_trade_opened,
    notify_trade_closed,
    notify_daily_report,
    notify_error,
    notify_bot_started,
    TELEGRAM_ENABLED
)
from trade_logger import log_trade_opened, log_trade_closed

# ============================================================================
# CONFIGURATION
# ============================================================================

# OANDA API Configuration (DEMO ACCOUNT for validation)
# Note: The API key works for both live and demo accounts
# The account ID determines which account is used
OANDA_API_KEY = os.getenv("OANDA_API_KEY", "08c10311c9d6136650e48bc25eb5980f-a295f483296c61be40ce577472e96153")
OANDA_ACCOUNT_ID_DEMO = "001-004-20593634-002"  # DEMO account
OANDA_ACCOUNT_ID_LIVE = "001-004-20593634-003"  # LIVE account

# SOFT LAUNCH MODE: Live trading with conservative settings for 24-hour validation
USE_DEMO = False  # LIVE TRADING
OANDA_ACCOUNT_ID = OANDA_ACCOUNT_ID_LIVE  # Using LIVE account
OANDA_ENVIRONMENT = "live"

# API Base URL
OANDA_BASE_URL = "https://api-fxtrade.oanda.com"  # LIVE endpoint

# Trading Configuration — SOFT LAUNCH (Conservative)
INSTRUMENTS = ["EUR_USD", "GBP_USD", "USD_JPY"]  # 3 pairs for diversification
BASE_POSITION_SIZE = 2000  # 0.02 lot = 2000 units (4x soft launch size)
MAX_POSITIONS_PER_PAIR = 1
MAX_TOTAL_POSITIONS = 3  # Max 3 positions total (1 per pair)

# Strategy Parameters
RSI_PERIOD = 14
RSI_OVERSOLD = 50  # Widened from 30 to generate more signals
RSI_OVERBOUGHT = 50  # Widened from 70 to generate more signals
BB_PERIOD = 20
BB_STD_DEV = 2.0
ATR_PERIOD = 14

# Risk Management — SOFT LAUNCH (Ultra-Conservative)
RISK_REWARD_RATIO = 1.5  # 1:1.5 R:R
DAILY_LOSS_LIMIT_PCT = 2.0  # Close all if daily loss exceeds 2% (£2 on £100 account)
MAX_SPREAD_PIPS = {
    "EUR_USD": 2.0,
    "GBP_USD": 2.5,
    "USD_JPY": 2.0
}

# Session Times (UTC) — 24/5 TRADING (No session filter)
LONDON_NY_OVERLAP_START = 13  # 1 PM UTC
LONDON_NY_OVERLAP_END = 16    # 4 PM UTC
STRICT_SESSION_FILTER = False  # Trade 24/5 for maximum opportunities

# Momentum Filter — Only trade when market is moving
MIN_ATR_MULTIPLIER = 0.5  # Only trade if ATR > 0.5x average ATR

# Logging
LOG_FILE = "/home/ubuntu/mean_reversion_bot.log"
REPORT_DIR = "/home/ubuntu/trading_reports"
os.makedirs(REPORT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# OANDA API HELPERS
# ============================================================================

def oanda_request(endpoint, method="GET", data=None):
    """Make authenticated request to OANDA API."""
    url = f"{OANDA_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339"
    }
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data, timeout=10)
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            logger.error(f"OANDA API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"OANDA request failed: {e}")
        return None


def get_account_info():
    """Get account balance and details."""
    data = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}")
    if data and "account" in data:
        account = data["account"]
        return {
            "balance": float(account.get("balance", 0)),
            "nav": float(account.get("NAV", 0)),
            "currency": account.get("currency", "USD"),
            "open_trade_count": int(account.get("openTradeCount", 0)),
            "unrealized_pl": float(account.get("unrealizedPL", 0))
        }
    return None


def get_candles(instrument, granularity="M15", count=100):
    """Fetch historical candles for indicator calculation."""
    endpoint = f"/v3/instruments/{instrument}/candles"
    params = f"?granularity={granularity}&count={count}"
    data = oanda_request(endpoint + params)
    
    if data and "candles" in data:
        candles = []
        for c in data["candles"]:
            if c["complete"]:
                candles.append({
                    "time": c["time"],
                    "open": float(c["mid"]["o"]),
                    "high": float(c["mid"]["h"]),
                    "low": float(c["mid"]["l"]),
                    "close": float(c["mid"]["c"]),
                    "volume": int(c["volume"])
                })
        return candles
    return []


def get_current_price(instrument):
    """Get current bid/ask pricing."""
    data = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}/pricing?instruments={instrument}")
    if data and "prices" in data and len(data["prices"]) > 0:
        price_data = data["prices"][0]
        return {
            "instrument": instrument,
            "bid": float(price_data["bids"][0]["price"]),
            "ask": float(price_data["asks"][0]["price"]),
            "spread": float(price_data["asks"][0]["price"]) - float(price_data["bids"][0]["price"]),
            "time": price_data["time"]
        }
    return None


def get_open_trades(instrument=None):
    """Get all open trades, optionally filtered by instrument."""
    data = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}/openTrades")
    if data and "trades" in data:
        trades = data["trades"]
        if instrument:
            trades = [t for t in trades if t["instrument"] == instrument]
        return trades
    return []


def place_market_order(instrument, units, sl_price, tp_price):
    """Place a market order with SL and TP."""
    order_data = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "stopLossOnFill": {"price": f"{sl_price:.5f}"},
            "takeProfitOnFill": {"price": f"{tp_price:.5f}"}
        }
    }
    
    result = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}/orders", method="POST", data=order_data)
    if result and "orderFillTransaction" in result:
        return result["orderFillTransaction"]
    return None


def modify_trade_sl(trade_id, new_sl):
    """Modify stop loss for an existing trade."""
    data = {
        "stopLoss": {
            "price": f"{new_sl:.5f}"
        }
    }
    result = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/orders", method="PUT", data=data)
    return result is not None


def close_trade(trade_id):
    """Close a specific trade."""
    result = oanda_request(f"/v3/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/close", method="PUT")
    return result is not None


# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================

def calculate_rsi(candles, period=14):
    """Calculate RSI indicator."""
    if len(candles) < period + 1:
        return None
    
    closes = [c["close"] for c in candles]
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_bollinger_bands(candles, period=20, std_dev=2.0):
    """Calculate Bollinger Bands."""
    if len(candles) < period:
        return None, None, None
    
    closes = [c["close"] for c in candles[-period:]]
    sma = sum(closes) / period
    
    variance = sum((x - sma) ** 2 for x in closes) / period
    std = math.sqrt(variance)
    
    upper_band = sma + (std_dev * std)
    lower_band = sma - (std_dev * std)
    
    return upper_band, sma, lower_band


def calculate_atr(candles, period=14):
    """Calculate Average True Range."""
    if len(candles) < period + 1:
        return None
    
    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    atr = sum(true_ranges[-period:]) / period
    return atr


# ============================================================================
# TRADING LOGIC
# ============================================================================

class TradeManager:
    """Manage open positions and track daily P/L."""
    
    def __init__(self):
        self.daily_trades = []
        self.daily_pnl = 0.0
        self.starting_balance = 0.0
        self.positions = {}  # {instrument: {trade_id, entry_price, sl, tp, direction}}
        
        # Auto-scaling tracking
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.position_size_multiplier = 1.0  # 1.0 = base size, 2.0 = double
        
        # Circuit breaker
        self.circuit_breaker_active = False
        self.circuit_breaker_until = None  # datetime when trading resumes
        self.circuit_breaker_pause_hours = 4
    
    def update_starting_balance(self):
        """Update starting balance at beginning of day."""
        account = get_account_info()
        if account:
            self.starting_balance = account["balance"]
    
    def check_daily_loss_limit(self):
        """Check if daily loss limit exceeded."""
        account = get_account_info()
        if account and self.starting_balance > 0:
            current_balance = account["balance"]
            loss_pct = ((self.starting_balance - current_balance) / self.starting_balance) * 100
            
            if loss_pct >= DAILY_LOSS_LIMIT_PCT:
                logger.warning(f"DAILY LOSS LIMIT EXCEEDED: {loss_pct:.2f}% loss")
                return True
        return False
    
    def add_position(self, instrument, trade_id, entry_price, sl, tp, direction, units):
        """Track new position."""
        self.positions[instrument] = {
            "trade_id": trade_id,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "direction": direction,
            "units": units,
            "opened_at": datetime.now(timezone.utc)
        }
    
    def remove_position(self, instrument, exit_price=None, pnl=None):
        """Remove closed position and log to database."""
        if instrument in self.positions:
            pos = self.positions[instrument]
            # Log trade closure to database if we have the DB trade ID
            if "db_trade_id" in pos and exit_price and pnl is not None:
                try:
                    log_trade_closed(
                        trade_id=pos["db_trade_id"],
                        exit_price=exit_price,
                        pnl=pnl
                    )
                except Exception as e:
                    logger.error(f"Failed to log trade closure to database: {e}")
            
            # Record trade result for auto-scaling
            if pnl is not None:
                self.record_trade_result(pnl)
            
            del self.positions[instrument]
    
    def has_position(self, instrument):
        """Check if we have an open position in this instrument."""
        return instrument in self.positions
    
    def get_position(self, instrument):
        """Get position details."""
        return self.positions.get(instrument)
    
    def sync_positions_with_oanda(self):
        """Sync local position tracking with actual OANDA positions."""
        logger.info("Syncing positions with OANDA...")
        open_trades = get_open_trades()
        oanda_instruments = {t["instrument"] for t in open_trades}
        
        # Remove positions that don't exist in OANDA
        for instrument in list(self.positions.keys()):
            if instrument not in oanda_instruments:
                logger.warning(f"Removing phantom position for {instrument} (not in OANDA)")
                del self.positions[instrument]
        
        logger.info(f"Position sync complete. Tracked: {len(self.positions)}, OANDA: {len(open_trades)}")
        return len(self.positions)
    
    def record_trade_result(self, pnl):
        """Record trade result and update auto-scaling multiplier."""
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            
            # Scale up after 20 consecutive wins
            if self.consecutive_wins >= 20 and self.position_size_multiplier < 2.0:
                self.position_size_multiplier = 2.0
                logger.info(f"🚀 AUTO-SCALING UP: Position size doubled after {self.consecutive_wins} wins")
                if TELEGRAM_ENABLED:
                    try:
                        from telegram_notifier import notify_error
                        notify_error(f"🚀 Position size DOUBLED after {self.consecutive_wins} consecutive wins!")
                    except:
                        pass
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            
            # Scale down after 3 consecutive losses
            if self.consecutive_losses >= 3 and self.position_size_multiplier > 1.0:
                self.position_size_multiplier = 1.0
                logger.warning(f"⚠️ AUTO-SCALING DOWN: Position size reset after {self.consecutive_losses} losses")
                if TELEGRAM_ENABLED:
                    try:
                        from telegram_notifier import notify_error
                        notify_error(f"⚠️ Position size RESET after {self.consecutive_losses} consecutive losses")
                    except:
                        pass
            
            # Circuit breaker: pause trading after 5 consecutive losses
            if self.consecutive_losses >= 5 and not self.circuit_breaker_active:
                self.activate_circuit_breaker()
    
    def get_scaled_position_size(self, base_size):
        """Get position size with auto-scaling multiplier applied."""
        return int(base_size * self.position_size_multiplier)
    
    def activate_circuit_breaker(self):
        """Activate circuit breaker to pause trading."""
        self.circuit_breaker_active = True
        self.circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=self.circuit_breaker_pause_hours)
        
        resume_time = self.circuit_breaker_until.strftime("%Y-%m-%d %H:%M UTC")
        logger.error(f"🛑 CIRCUIT BREAKER ACTIVATED: Trading paused for {self.circuit_breaker_pause_hours}h after {self.consecutive_losses} losses. Resume at {resume_time}")
        
        if TELEGRAM_ENABLED:
            try:
                from telegram_notifier import notify_error
                notify_error(
                    f"🛑 CIRCUIT BREAKER ACTIVATED\n\n"
                    f"Trading paused for {self.circuit_breaker_pause_hours} hours after {self.consecutive_losses} consecutive losses.\n\n"
                    f"Resume time: {resume_time}\n\n"
                    f"This protects your capital during unfavorable market conditions."
                )
            except Exception as e:
                logger.error(f"Failed to send circuit breaker notification: {e}")
    
    def check_circuit_breaker(self):
        """Check if circuit breaker should be deactivated."""
        if self.circuit_breaker_active and self.circuit_breaker_until:
            now = datetime.now(timezone.utc)
            if now >= self.circuit_breaker_until:
                self.circuit_breaker_active = False
                self.circuit_breaker_until = None
                logger.info("✅ CIRCUIT BREAKER DEACTIVATED: Trading resumed")
                
                if TELEGRAM_ENABLED:
                    try:
                        from telegram_notifier import notify_error
                        notify_error(
                            f"✅ CIRCUIT BREAKER DEACTIVATED\n\n"
                            f"Trading has automatically resumed after {self.circuit_breaker_pause_hours}h pause.\n\n"
                            f"Consecutive loss counter reset. Good luck!"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send resume notification: {e}")
                
                return False  # Not active
            return True  # Still active
        return False  # Not active


trade_mgr = TradeManager()


def is_high_volume_session():
    """Check if current time is during London/NY overlap."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    return LONDON_NY_OVERLAP_START <= hour < LONDON_NY_OVERLAP_END


def calculate_position_size(instrument, atr):
    """Calculate dynamic position size based on ATR volatility with auto-scaling."""
    pip_value = 0.0001 if "JPY" not in instrument else 0.01
    atr_pips = atr / pip_value
    
    # Base size calculation based on volatility
    if atr_pips < 10:
        base_size = int(BASE_POSITION_SIZE * 1.5)  # Lower volatility
    elif atr_pips > 20:
        base_size = int(BASE_POSITION_SIZE * 0.5)  # Higher volatility
    else:
        base_size = BASE_POSITION_SIZE  # Normal volatility
    
    # Apply auto-scaling multiplier
    return trade_mgr.get_scaled_position_size(base_size)


def check_spread(instrument, pricing):
    """Check if spread is acceptable."""
    pip_value = 0.0001 if "JPY" not in instrument else 0.01
    spread_pips = pricing["spread"] / pip_value
    max_spread = MAX_SPREAD_PIPS.get(instrument, 2.0)
    
    return spread_pips <= max_spread


def analyze_instrument(instrument):
    """Analyze single instrument for entry signals."""
    try:
        # Fetch candles
        candles = get_candles(instrument, "M15", 100)
        if len(candles) < 50:
            logger.warning(f"{instrument}: Not enough candles for analysis")
            return None
        
        # Calculate indicators
        rsi = calculate_rsi(candles, RSI_PERIOD)
        upper_bb, middle_bb, lower_bb = calculate_bollinger_bands(candles, BB_PERIOD, BB_STD_DEV)
        atr = calculate_atr(candles, ATR_PERIOD)
        
        if None in [rsi, upper_bb, lower_bb, atr]:
            logger.warning(f"{instrument}: Indicator calculation failed")
            return None
        
        current_price = candles[-1]["close"]
        pip_value = 0.0001 if "JPY" not in instrument else 0.01
        
        # Get live pricing
        pricing = get_current_price(instrument)
        if not pricing:
            return None
        
        # Check spread
        if not check_spread(instrument, pricing):
            logger.debug(f"{instrument}: Spread too wide ({pricing['spread']/pip_value:.1f} pips)")
            return None
        
        # Momentum Filter: Only trade when market is moving (ATR check)
        # Calculate average ATR over last 20 periods
        atr_values = []
        for i in range(len(candles)-30, len(candles)-ATR_PERIOD):
            atr_val = calculate_atr(candles[i:i+ATR_PERIOD+1], ATR_PERIOD)
            if atr_val:
                atr_values.append(atr_val)
        
        if atr_values:
            avg_atr = sum(atr_values) / len(atr_values)
            if atr < avg_atr * MIN_ATR_MULTIPLIER:
                logger.debug(f"{instrument}: Low momentum (ATR {atr:.5f} < {avg_atr * MIN_ATR_MULTIPLIER:.5f})")
                return None
        
        # Calculate position size
        position_size = calculate_position_size(instrument, atr)
        
        # BUY SIGNAL: RSI oversold + price at/below lower BB
        if rsi < RSI_OVERSOLD and current_price <= lower_bb * 1.001:
            sl_distance = atr * 1.5
            sl_price = pricing["ask"] - sl_distance
            tp_price = middle_bb  # Target middle BB
            
            return {
                "action": "BUY",
                "instrument": instrument,
                "entry_price": pricing["ask"],
                "sl": sl_price,
                "tp": tp_price,
                "units": position_size,
                "rsi": rsi,
                "bb_position": "lower",
                "atr": atr
            }
        
        # SELL SIGNAL: RSI overbought + price at/above upper BB
        elif rsi > RSI_OVERBOUGHT and current_price >= upper_bb * 0.999:
            sl_distance = atr * 1.5
            sl_price = pricing["bid"] + sl_distance
            tp_price = middle_bb  # Target middle BB
            
            return {
                "action": "SELL",
                "instrument": instrument,
                "entry_price": pricing["bid"],
                "sl": sl_price,
                "tp": tp_price,
                "units": -position_size,  # Negative for sell
                "rsi": rsi,
                "bb_position": "upper",
                "atr": atr
            }
        
        return None
    
    except Exception as e:
        logger.error(f"{instrument} analysis error: {e}")
        return None


def execute_trade(signal):
    """Execute trade based on signal."""
    instrument = signal["instrument"]
    
    # Check if we already have a position
    if trade_mgr.has_position(instrument):
        logger.debug(f"{instrument}: Already have open position, skipping")
        return False
    
    # Check daily loss limit
    if trade_mgr.check_daily_loss_limit():
        logger.warning("Daily loss limit exceeded, no new trades")
        return False
    
    # Place order
    result = place_market_order(
        instrument,
        signal["units"],
        signal["sl"],
        signal["tp"]
    )
    
    if result:
        trade_id = result.get("id")
        entry_price = float(result.get("price", signal["entry_price"]))
        
        logger.info(f"✓ {signal['action']} {instrument} @ {entry_price:.5f}")
        logger.info(f"  Units: {signal['units']} | SL: {signal['sl']:.5f} | TP: {signal['tp']:.5f}")
        logger.info(f"  RSI: {signal['rsi']:.1f} | BB: {signal['bb_position']} | ATR: {signal['atr']:.5f}")
        
        # Track position
        trade_mgr.add_position(
            instrument,
            trade_id,
            entry_price,
            signal["sl"],
            signal["tp"],
            signal["action"],
            signal["units"]
        )
        
        # Log trade to database
        try:
            db_trade_id = log_trade_opened(
                bot="mean-reversion",
                pair=instrument,
                direction=signal["action"],
                signal_type=f"RSI {signal['rsi']:.1f} + BB {signal['bb_position']}",
                entry_price=entry_price,
                units=signal["units"],
                stop_loss=signal["sl"],
                take_profit=signal["tp"],
                metadata={"atr": signal["atr"], "rsi": signal["rsi"]}
            )
            # Store DB trade ID in position for later update
            if db_trade_id:
                trade_mgr.positions[instrument]["db_trade_id"] = db_trade_id
        except Exception as e:
            logger.error(f"Database logging failed: {e}")
        
        # Send Telegram notification
        if TELEGRAM_ENABLED:
            try:
                pip_value = 0.0001 if "JPY" not in instrument else 0.01
                sl_pips = abs(entry_price - signal["sl"]) / pip_value
                tp_pips = abs(signal["tp"] - entry_price) / pip_value
                
                notify_trade_opened(
                    instrument,
                    signal["action"],
                    entry_price,
                    signal["sl"],
                    signal["tp"],
                    signal["units"],
                    f"RSI {signal['rsi']:.1f} + BB {signal['bb_position']}"
                )
            except Exception as e:
                logger.error(f"Telegram notification failed: {e}")
        
        return True
    
    return False


def check_trailing_stops():
    """Check if any positions should move SL to breakeven or trail."""
    for instrument, pos in list(trade_mgr.positions.items()):
        try:
            pricing = get_current_price(instrument)
            if not pricing:
                continue
            
            current_price = pricing["bid"] if pos["direction"] == "BUY" else pricing["ask"]
            entry = pos["entry_price"]
            tp = pos["tp"]
            current_sl = pos["sl"]
            
            # Calculate profit percentage toward TP
            if pos["direction"] == "BUY":
                total_distance = tp - entry
                current_profit = current_price - entry
            else:
                total_distance = entry - tp
                current_profit = entry - current_price
            
            if total_distance <= 0:
                continue
            
            profit_pct = (current_profit / total_distance) * 100
            
            # Move to breakeven at 50% profit
            if profit_pct >= 50 and current_sl != entry:
                logger.info(f"{instrument}: Moving SL to breakeven (50% profit reached)")
                if modify_trade_sl(pos["trade_id"], entry):
                    pos["sl"] = entry
                    if TELEGRAM_ENABLED:
                        notify_sl_stage_change(instrument, "breakeven", entry)
            
            # Trail to 50% profit at 75% toward TP
            elif profit_pct >= 75:
                new_sl = entry + (total_distance * 0.5) if pos["direction"] == "BUY" else entry - (total_distance * 0.5)
                if abs(new_sl - current_sl) > 0.0001:
                    logger.info(f"{instrument}: Trailing SL to 50% profit (75% toward TP)")
                    if modify_trade_sl(pos["trade_id"], new_sl):
                        pos["sl"] = new_sl
                        if TELEGRAM_ENABLED:
                            notify_sl_stage_change(instrument, "50% profit", new_sl)
        
        except Exception as e:
            logger.error(f"Trailing stop check error for {instrument}: {e}")


def scan_all_instruments():
    """Scan all instruments for trading opportunities."""
    logger.info("=" * 70)
    logger.info("MARKET SCAN — Mean-Reversion Strategy")
    logger.info("=" * 70)
    
    account = get_account_info()
    if account:
        logger.info(f"Account Balance: {account['balance']:.2f} {account['currency']}")
        logger.info(f"Open Positions: {account['open_trade_count']}")
        logger.info(f"Unrealized P/L: {account['unrealized_pl']:.2f}")
    
    session_status = "ACTIVE (London/NY Overlap)" if is_high_volume_session() else "Outside primary session"
    logger.info(f"Session: {session_status}")
    logger.info("-" * 70)
    
    # Check daily loss limit
    if trade_mgr.check_daily_loss_limit():
        logger.warning("Daily loss limit exceeded — closing all positions")
        for instrument in INSTRUMENTS:
            trades = get_open_trades(instrument)
            for trade in trades:
                close_trade(trade["id"])
                trade_mgr.remove_position(instrument)
        return
    
    # Scan each instrument
    signals = []
    for instrument in INSTRUMENTS:
        signal = analyze_instrument(instrument)
        if signal:
            signals.append(signal)
    
    # Execute signals
    if signals:
        logger.info(f"Found {len(signals)} signal(s)")
        for signal in signals:
            execute_trade(signal)
    else:
        logger.info("No signals generated")
    
    # Check trailing stops
    check_trailing_stops()
    
    logger.info("=" * 70)


# ============================================================================
# SCHEDULED TASKS
# ============================================================================

def periodic_scan():
    """Run market scan every 15 minutes."""
    # Check if circuit breaker should be deactivated
    if trade_mgr.check_circuit_breaker():
        logger.warning("🛑 Circuit breaker active - skipping scan")
        return
    
    scan_all_instruments()


def daily_report():
    """Generate end-of-day report."""
    logger.info("=" * 70)
    logger.info("END OF DAY REPORT")
    logger.info("=" * 70)
    
    account = get_account_info()
    if account:
        daily_pnl = account["balance"] - trade_mgr.starting_balance
        
        logger.info(f"Starting Balance: {trade_mgr.starting_balance:.2f}")
        logger.info(f"Ending Balance: {account['balance']:.2f}")
        logger.info(f"Daily P/L: {daily_pnl:+.2f}")
        logger.info(f"Total Trades: {len(trade_mgr.daily_trades)}")
        
        # Send Telegram report
        if TELEGRAM_ENABLED:
            try:
                notify_daily_report(
                    len(trade_mgr.daily_trades),
                    daily_pnl,
                    account["balance"]
                )
            except Exception as e:
                logger.error(f"Telegram notification failed: {e}")
    
    # Reset for next day
    trade_mgr.daily_trades = []
    trade_mgr.update_starting_balance()
    
    logger.info("=" * 70)


# ============================================================================
# FLASK API
# ============================================================================

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    account = get_account_info()
    return jsonify({
        "status": "healthy",
        "strategy": "Mean-Reversion (RSI + BB)",
        "pairs": INSTRUMENTS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_balance": account["balance"] if account else "N/A",
        "open_positions": len(trade_mgr.positions),
        "session_active": is_high_volume_session()
    }), 200


@app.route('/status', methods=['GET'])
def status():
    """Get detailed bot status."""
    account = get_account_info()
    return jsonify({
        "status": "running",
        "strategy": "Mean-Reversion",
        "pairs": INSTRUMENTS,
        "environment": OANDA_ENVIRONMENT,
        "positions": [
            {
                "instrument": inst,
                "direction": pos["direction"],
                "entry_price": pos["entry_price"],
                "sl": pos["sl"],
                "tp": pos["tp"],
                "units": pos["units"]
            }
            for inst, pos in trade_mgr.positions.items()
        ],
        "account": account,
        "daily_trades": len(trade_mgr.daily_trades),
        "daily_pnl": account["balance"] - trade_mgr.starting_balance if account else 0
    }), 200


@app.route('/scan', methods=['POST'])
def manual_scan():
    """Trigger manual market scan."""
    logger.info("MANUAL SCAN TRIGGERED")
    scan_all_instruments()
    return jsonify({"status": "scan_complete"}), 200


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    logger.info("╔" + "═" * 68 + "╗")
    logger.info("║  MEAN-REVERSION BOT — RSI + BOLLINGER BANDS                        ║")
    logger.info("║  Strategy: Counter-trend mean-reversion with layered filtering     ║")
    logger.info("║  Mode: LIVE AGGRESSIVE (24/5 trading, widened RSI, 4x position size) ║")
    logger.info("╚" + "═" * 68 + "╝")
    logger.info(f"  Environment:    {OANDA_ENVIRONMENT.upper()}")
    logger.info(f"  Account:        {OANDA_ACCOUNT_ID}")
    logger.info(f"  Pairs:          {', '.join(INSTRUMENTS)}")
    logger.info(f"  Timeframe:      M15 (15-minute candles)")
    logger.info(f"  RSI:            Period={RSI_PERIOD}, Oversold<{RSI_OVERSOLD}, Overbought>{RSI_OVERBOUGHT}")
    logger.info(f"  Bollinger:      Period={BB_PERIOD}, StdDev={BB_STD_DEV}")
    logger.info(f"  Session:        24/5 Trading (No session filter)")
    logger.info(f"  Position Size:  {BASE_POSITION_SIZE} units (dynamic based on ATR)")
    logger.info("─" * 70)
    
    # Verify OANDA connection
    account = get_account_info()
    if account:
        logger.info(f"  ✓ OANDA CONNECTED | Balance: {account['balance']:.2f} {account['currency']}")
        trade_mgr.update_starting_balance()
        
        # Sync positions to fix phantom position bug
        trade_mgr.sync_positions_with_oanda()
        
        # Send Telegram bot started notification
        if TELEGRAM_ENABLED:
            try:
                notify_bot_started(account['balance'], OANDA_ENVIRONMENT)
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")
    else:
        logger.error("  ✗ OANDA CONNECTION FAILED")
    
    # Schedule tasks
    schedule.every(15).minutes.do(periodic_scan)  # Scan every 15 minutes
    schedule.every().day.at("20:00").do(daily_report)  # Daily report at 8 PM UTC
    
    # Run initial scan
    logger.info("Running initial market scan...")
    scan_all_instruments()
    
    # Start scheduler in background
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start Flask server
    logger.info("Starting API server on port 5001...")
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
