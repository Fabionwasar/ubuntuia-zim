#!/usr/bin/env python3
"""
London Fortress — OANDA Automated Trading Bot
===============================================
Strategy: London Fortress (GBP/USD Specialist)
Timeframes: Daily (trend filter) + H4 (confirmation) + H1 (entry)
Broker: OANDA REST v20 API (LIVE)

Features:
- Multi-timeframe analysis (Daily 50 EMA + H4 Supertrend/ADX + H1 entries)
- London Breakout detection (Asian session range)
- Trade stacking: 5x 0.01 lot positions per entry signal
- Progressive SL management: Breakeven +10p → 25% → 50% → 75% toward TP
- EMA Cross (9/21) momentum confirmation
- RSI pullback entries
- Session-based trading (8AM-8PM UK time)
- End-of-day position closure
- TradingView webhook receiver for automated execution
- Comprehensive logging and daily reporting

Author: Manus AI — London Fortress System
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

# ============================================================================
# CONFIGURATION
# ============================================================================

# OANDA API Configuration (LIVE ACCOUNT)
OANDA_API_KEY = os.getenv("OANDA_API_KEY", "08c10311c9d6136650e48bc25eb5980f-a295f483296c61be40ce577472e96153")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "001-004-20593634-003")
OANDA_ENVIRONMENT = "live"  # LIVE trading — NO DEMO

# API Base URL
OANDA_BASE_URL = "https://api-fxtrade.oanda.com"

# Trading Configuration — GBP/USD ONLY
INSTRUMENT = "GBP_USD"
POSITION_SIZE_PER_STACK = 100  # 0.01 lot = 100 units for OANDA
MAX_STACK_TRADES = 5           # Stack 5 trades per entry signal
RISK_REWARD_RATIO = 2.5        # 1:2.5 R:R

# Indicator Settings
DAILY_EMA_LEN = 50       # Daily 50 EMA (institutional trend filter)
H4_ATR_PERIOD = 20       # H4 Supertrend ATR period
H4_ATR_FACTOR = 3.5      # H4 Supertrend factor
H4_ADX_LEN = 14          # H4 ADX length
H4_ADX_THRESHOLD = 15    # Minimum ADX for trending market (AGGRESSIVE: lowered from 20)
FAST_EMA = 9             # H1 fast EMA
SLOW_EMA = 21            # H1 slow EMA
RSI_LEN = 14             # H1 RSI length
RSI_BUY_ZONE = 45        # RSI below this = pullback buy opportunity (AGGRESSIVE: raised from 40)
RSI_SELL_ZONE = 55       # RSI above this = pullback sell opportunity (AGGRESSIVE: lowered from 60)

# London Breakout Settings
ASIAN_START_HOUR = 0     # Asian session start (UTC)
ASIAN_END_HOUR = 8       # Asian session end / London open (UTC)
BREAKOUT_BUFFER_PIPS = 2 # Extra pips beyond Asian range (AGGRESSIVE: lowered from 5)

# Progressive SL Settings
BREAKEVEN_PIPS = 10      # Move SL to breakeven + this many pips
SL_TRAIL_25 = True       # Trail SL to 25% toward TP
SL_TRAIL_50 = True       # Trail SL to 50% toward TP
SL_TRAIL_75 = True       # Trail SL to 75% toward TP

# Market Hours (UTC) — 8AM to 8PM UK time
LONDON_OPEN_HOUR = 8
US_OPEN_HOUR = 13
TRADING_END_HOUR = 20

# Risk Management
MAX_SPREAD_PIPS = 3.0    # Max spread to enter trade
SL_BUFFER_PIPS = 5       # Extra buffer added to SL
CLOSE_ON_OPPOSITE = True # Close position on strong opposite signal
CLOSE_AT_EOD = True      # Close all positions at 8PM UK

# Logging
LOG_FILE = "/home/ubuntu/london_fortress.log"
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
logger = logging.getLogger("LondonFortress")

# ============================================================================
# TRADE STATE TRACKING
# ============================================================================

class TradeManager:
    """Manages open trades, stacking, and progressive SL."""
    
    def __init__(self):
        self.active_trades = {}  # trade_id -> trade_info
        self.entry_price = None
        self.direction = None    # "BUY" or "SELL"
        self.initial_sl = None
        self.take_profit = None
        self.current_sl = None
        self.sl_stage = 0        # 0=initial, 1=breakeven, 2=25%, 3=50%, 4=75%
        self.stack_count = 0
        self.daily_trades = []   # Track all trades today for reporting
        self.daily_pnl = 0.0
        
    def reset(self):
        """Reset state when all trades are closed."""
        self.active_trades = {}
        self.entry_price = None
        self.direction = None
        self.initial_sl = None
        self.take_profit = None
        self.current_sl = None
        self.sl_stage = 0
        self.stack_count = 0
        
    def record_trade(self, trade_id, direction, entry_price, sl, tp, units):
        """Record a new trade."""
        self.active_trades[trade_id] = {
            "direction": direction,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "units": units,
            "time": datetime.now(timezone.utc).isoformat()
        }
        if self.entry_price is None:
            self.entry_price = entry_price
            self.direction = direction
            self.initial_sl = sl
            self.take_profit = tp
            self.current_sl = sl
            self.sl_stage = 0
        self.stack_count = len(self.active_trades)
        
    def remove_trade(self, trade_id, pnl=0):
        """Remove a closed trade."""
        if trade_id in self.active_trades:
            del self.active_trades[trade_id]
            self.daily_pnl += pnl
        if len(self.active_trades) == 0:
            self.reset()
            
    def get_sl_stage_name(self):
        """Get human-readable SL stage name."""
        names = {0: "INITIAL", 1: "BREAKEVEN +10p", 2: "25% TO TP", 3: "50% TO TP", 4: "75% TO TP"}
        return names.get(self.sl_stage, "UNKNOWN")

# Global trade manager
trade_mgr = TradeManager()

# Asian session range tracking
asian_range = {
    "high": None,
    "low": None,
    "locked": False,
    "date": None
}


# ============================================================================
# OANDA API FUNCTIONS
# ============================================================================

def get_headers():
    """Return OANDA API headers with authentication."""
    return {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339"
    }


def get_account_info():
    """Get account balance and details."""
    try:
        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/summary"
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            account = data.get("account", {})
            return {
                "balance": float(account.get("balance", 0)),
                "unrealized_pl": float(account.get("unrealizedPL", 0)),
                "nav": float(account.get("NAV", 0)),
                "open_trade_count": int(account.get("openTradeCount", 0)),
                "margin_used": float(account.get("marginUsed", 0)),
                "margin_available": float(account.get("marginAvailable", 0)),
                "currency": account.get("currency", "GBP")
            }
        else:
            logger.error(f"Account info error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception getting account info: {e}")
        return None


def get_candles(granularity, count=100):
    """Fetch candlestick data from OANDA for GBP/USD."""
    try:
        url = f"{OANDA_BASE_URL}/v3/instruments/{INSTRUMENT}/candles"
        params = {
            "granularity": granularity,
            "count": count,
            "price": "MBA"
        }
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("candles", [])
            complete_candles = [c for c in candles if c.get("complete", False)]
            return complete_candles
        else:
            logger.error(f"Candle fetch error {granularity}: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        logger.error(f"Exception fetching candles: {e}")
        return []


def get_current_price():
    """Get current bid/ask price for GBP/USD."""
    try:
        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/pricing"
        params = {"instruments": INSTRUMENT}
        response = requests.get(url, headers=get_headers(), params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            prices = data.get("prices", [])
            if prices:
                bid = float(prices[0]["bids"][0]["price"])
                ask = float(prices[0]["asks"][0]["price"])
                spread = ask - bid
                return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "spread": spread}
        logger.warning(f"Could not get price for {INSTRUMENT}")
        return None
    except Exception as e:
        logger.error(f"Exception getting price: {e}")
        return None


def get_open_trades():
    """Get open trades for GBP/USD."""
    try:
        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/openTrades"
        response = requests.get(url, headers=get_headers(), timeout=5)
        if response.status_code == 200:
            trades = response.json().get("trades", [])
            return [t for t in trades if t.get("instrument") == INSTRUMENT]
        return []
    except Exception as e:
        logger.error(f"Exception getting trades: {e}")
        return []


def execute_market_order(direction, units, sl_price=None, tp_price=None, comment=""):
    """Execute a single market order on OANDA."""
    try:
        order_units = str(units) if direction.upper() == "BUY" else str(-units)
        
        order_data = {
            "order": {
                "instrument": INSTRUMENT,
                "units": order_units,
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT"
            }
        }

        if tp_price and tp_price > 0:
            order_data["order"]["takeProfitOnFill"] = {
                "price": f"{tp_price:.5f}"
            }

        if sl_price and sl_price > 0:
            order_data["order"]["stopLossOnFill"] = {
                "price": f"{sl_price:.5f}"
            }

        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
        response = requests.post(url, headers=get_headers(), json=order_data, timeout=10)

        if response.status_code in [200, 201]:
            result = response.json()
            fill = result.get("orderFillTransaction", {})
            fill_price = fill.get("price", "N/A")
            trade_id = fill.get("tradeOpened", {}).get("tradeID", "N/A")
            
            logger.info(f"  ✓ ORDER FILLED: {direction} {units} units @ {fill_price} | "
                        f"SL: {sl_price:.5f} | TP: {tp_price:.5f} | Trade ID: {trade_id} | {comment}")
            
            # Record in trade manager
            if trade_id != "N/A":
                trade_mgr.record_trade(trade_id, direction, float(fill_price), sl_price, tp_price, units)
            
            return {"success": True, "trade_id": trade_id, "fill_price": float(fill_price) if fill_price != "N/A" else 0}
        else:
            logger.error(f"  ✗ Order failed: {response.status_code} - {response.text}")
            return {"success": False, "error": response.text}

    except Exception as e:
        logger.error(f"  ✗ Exception executing order: {e}")
        return {"success": False, "error": str(e)}


def execute_stacked_trades(direction, sl_price, tp_price, signal_type="", strength=3):
    """Execute 5 stacked trades (0.01 lot each) for a single entry signal."""
    current_open = len(get_open_trades())
    trades_to_open = min(MAX_STACK_TRADES, MAX_STACK_TRADES - current_open)
    
    if trades_to_open <= 0:
        logger.info(f"  MAX STACK: Already have {current_open} open trades, skipping")
        return 0
    
    # For light signals, only open 3 trades
    if strength == 1:
        trades_to_open = min(3, trades_to_open)
    
    logger.info(f"  STACKING: Opening {trades_to_open}x {POSITION_SIZE_PER_STACK} units {direction}")
    
    successful = 0
    for i in range(trades_to_open):
        result = execute_market_order(
            direction, 
            POSITION_SIZE_PER_STACK, 
            sl_price, 
            tp_price,
            comment=f"Stack {i+1}/{trades_to_open} | {signal_type}"
        )
        if result["success"]:
            successful += 1
        time.sleep(0.3)  # Small delay between orders
    
    logger.info(f"  STACK RESULT: {successful}/{trades_to_open} trades opened")
    return successful


def modify_trade_sl(trade_id, new_sl):
    """Modify the stop loss of an existing trade."""
    try:
        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/orders"
        data = {
            "stopLoss": {
                "price": f"{new_sl:.5f}",
                "timeInForce": "GTC"
            }
        }
        response = requests.put(url, headers=get_headers(), json=data, timeout=10)
        if response.status_code == 200:
            return True
        else:
            logger.error(f"  SL modify failed for trade {trade_id}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"  Exception modifying SL: {e}")
        return False


def close_trade(trade_id):
    """Close a specific trade by ID."""
    try:
        url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/trades/{trade_id}/close"
        response = requests.put(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            result = response.json()
            pnl = float(result.get("orderFillTransaction", {}).get("pl", 0))
            logger.info(f"  ✓ TRADE CLOSED: {trade_id} | P/L: {pnl}")
            trade_mgr.remove_trade(trade_id, pnl)
            return True
        else:
            logger.error(f"  ✗ Close failed for {trade_id}: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"  Exception closing trade: {e}")
        return False


def close_all_trades(reason=""):
    """Close all open GBP/USD trades."""
    trades = get_open_trades()
    if not trades:
        logger.info(f"  No open trades to close ({reason})")
        return
    
    logger.info(f"  CLOSING ALL: {len(trades)} trades ({reason})")
    for trade in trades:
        close_trade(trade["id"])
    trade_mgr.reset()


# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================

def extract_ohlc(candles):
    """Extract OHLC arrays from OANDA candle data."""
    opens, highs, lows, closes, times = [], [], [], [], []
    for c in candles:
        mid = c.get("mid", {})
        opens.append(float(mid.get("o", 0)))
        highs.append(float(mid.get("h", 0)))
        lows.append(float(mid.get("l", 0)))
        closes.append(float(mid.get("c", 0)))
        times.append(c.get("time", ""))
    return opens, highs, lows, closes, times


def calculate_ema(data, period):
    """Calculate Exponential Moving Average."""
    if len(data) < period:
        return [None] * len(data)
    ema = [None] * len(data)
    multiplier = 2.0 / (period + 1)
    sma = sum(data[:period]) / period
    ema[period - 1] = sma
    for i in range(period, len(data)):
        ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def calculate_atr(highs, lows, closes, period):
    """Calculate Average True Range."""
    if len(highs) < period + 1:
        return [None] * len(highs)
    tr = [None] * len(highs)
    atr = [None] * len(highs)
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    if len(tr) >= period:
        first_atr = sum(t for t in tr[:period] if t is not None) / period
        atr[period - 1] = first_atr
        for i in range(period, len(tr)):
            if tr[i] is not None and atr[i-1] is not None:
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr


def calculate_supertrend(highs, lows, closes, atr_period, multiplier):
    """Calculate Supertrend indicator. Returns (supertrend_line, direction) arrays."""
    n = len(closes)
    atr = calculate_atr(highs, lows, closes, atr_period)
    upper_band = [None] * n
    lower_band = [None] * n
    supertrend = [None] * n
    direction = [0] * n

    for i in range(atr_period, n):
        if atr[i] is None:
            continue
        mid = (highs[i] + lows[i]) / 2.0
        basic_upper = mid + multiplier * atr[i]
        basic_lower = mid - multiplier * atr[i]

        if i > atr_period and lower_band[i-1] is not None:
            lower_band[i] = max(basic_lower, lower_band[i-1]) if closes[i-1] > lower_band[i-1] else basic_lower
        else:
            lower_band[i] = basic_lower

        if i > atr_period and upper_band[i-1] is not None:
            upper_band[i] = min(basic_upper, upper_band[i-1]) if closes[i-1] < upper_band[i-1] else basic_upper
        else:
            upper_band[i] = basic_upper

        if i == atr_period:
            direction[i] = -1
        else:
            prev_dir = direction[i-1]
            if prev_dir <= 0:
                direction[i] = 1 if closes[i] < lower_band[i] else -1
            else:
                direction[i] = -1 if closes[i] > upper_band[i] else 1

        supertrend[i] = lower_band[i] if direction[i] < 0 else upper_band[i]

    return supertrend, direction


def calculate_rsi(closes, period=14):
    """Calculate Relative Strength Index."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    
    rsi = [None] * len(closes)
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    
    if len(gains) < period:
        return rsi
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        rsi[period] = 100
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100 - (100 / (1 + rs))
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_adx(highs, lows, closes, period=14):
    """Calculate Average Directional Index."""
    n = len(closes)
    if n < period * 2:
        return [None] * n
    
    adx = [None] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    
    for i in range(1, n):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    
    # Smoothed values
    smooth_plus_dm = sum(plus_dm[1:period+1])
    smooth_minus_dm = sum(minus_dm[1:period+1])
    smooth_tr = sum(tr[1:period+1])
    
    dx_values = []
    
    for i in range(period, n):
        if i > period:
            smooth_plus_dm = smooth_plus_dm - smooth_plus_dm / period + plus_dm[i]
            smooth_minus_dm = smooth_minus_dm - smooth_minus_dm / period + minus_dm[i]
            smooth_tr = smooth_tr - smooth_tr / period + tr[i]
        
        if smooth_tr > 0:
            plus_di = 100 * smooth_plus_dm / smooth_tr
            minus_di = 100 * smooth_minus_dm / smooth_tr
        else:
            plus_di = 0
            minus_di = 0
        
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
        dx_values.append(dx)
        
        if len(dx_values) >= period:
            if len(dx_values) == period:
                adx[i] = sum(dx_values) / period
            else:
                adx[i] = (adx[i-1] * (period - 1) + dx) / period if adx[i-1] is not None else dx
    
    return adx


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

PIP_VALUE = 0.0001  # GBP/USD pip value

def pips_to_price(pips):
    return pips * PIP_VALUE

def price_to_pips(price_distance):
    return price_distance / PIP_VALUE if PIP_VALUE > 0 else 0

def is_trading_hours():
    """Check if current time is within trading hours (8AM-8PM UTC)."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()
    
    # Skip weekends
    if weekday >= 5:
        return False
    
    return LONDON_OPEN_HOUR <= hour < TRADING_END_HOUR

def is_london_session():
    """Check if we're in the London session (8AM-1PM UTC)."""
    now = datetime.now(timezone.utc)
    return LONDON_OPEN_HOUR <= now.hour < US_OPEN_HOUR

def is_us_session():
    """Check if we're in the US session (1PM-8PM UTC)."""
    now = datetime.now(timezone.utc)
    return US_OPEN_HOUR <= now.hour < TRADING_END_HOUR


# ============================================================================
# LONDON BREAKOUT RANGE
# ============================================================================

def update_asian_range():
    """Update the Asian session range from H1 candles."""
    global asian_range
    
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    
    # Only recalculate once per day
    if asian_range["date"] == today and asian_range["locked"]:
        return
    
    # Fetch H1 candles
    candles = get_candles("H1", count=24)
    if not candles:
        return
    
    session_high = None
    session_low = None
    
    for c in candles:
        candle_time = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
        candle_hour = candle_time.hour
        candle_date = candle_time.strftime("%Y-%m-%d")
        
        # Look for today's Asian session candles (0:00 - 8:00 UTC)
        if candle_date == today and ASIAN_START_HOUR <= candle_hour < ASIAN_END_HOUR:
            mid = c.get("mid", {})
            h = float(mid.get("h", 0))
            l = float(mid.get("l", 0))
            
            if session_high is None or h > session_high:
                session_high = h
            if session_low is None or l < session_low:
                session_low = l
    
    if session_high and session_low:
        asian_range["high"] = session_high
        asian_range["low"] = session_low
        asian_range["locked"] = True
        asian_range["date"] = today
        range_pips = price_to_pips(session_high - session_low)
        logger.info(f"  ASIAN RANGE: {session_high:.5f} / {session_low:.5f} ({range_pips:.1f} pips)")


def check_breakout():
    """Check if price has broken out of the Asian range."""
    if not asian_range["locked"] or asian_range["high"] is None:
        return None
    
    pricing = get_current_price()
    if not pricing:
        return None
    
    current = pricing["mid"]
    buffer = pips_to_price(BREAKOUT_BUFFER_PIPS)
    
    if current > asian_range["high"] + buffer:
        return "LONG_BREAKOUT"
    elif current < asian_range["low"] - buffer:
        return "SHORT_BREAKOUT"
    
    return None


# ============================================================================
# PROGRESSIVE STOP LOSS MANAGEMENT
# ============================================================================

def manage_progressive_sl():
    """
    Check all open trades and progressively move SL:
    Stage 0 → 1: When profit >= breakeven_pips, move SL to entry + breakeven_pips
    Stage 1 → 2: When profit >= 25% of TP distance, move SL to 25% toward TP
    Stage 2 → 3: When profit >= 50% of TP distance, move SL to 50% toward TP
    Stage 3 → 4: When profit >= 75% of TP distance, move SL to 75% toward TP
    """
    if trade_mgr.entry_price is None or trade_mgr.direction is None:
        return
    
    pricing = get_current_price()
    if not pricing:
        return
    
    current = pricing["mid"]
    entry = trade_mgr.entry_price
    tp = trade_mgr.take_profit
    direction = trade_mgr.direction
    
    if tp is None or entry is None:
        return
    
    tp_dist = abs(tp - entry)
    beven_value = pips_to_price(BREAKEVEN_PIPS)
    
    if direction == "BUY":
        current_profit = current - entry
    else:
        current_profit = entry - current
    
    new_sl = None
    new_stage = trade_mgr.sl_stage
    
    # Stage 0 → 1: Breakeven + 10 pips
    if trade_mgr.sl_stage == 0 and current_profit >= beven_value:
        if direction == "BUY":
            new_sl = entry + beven_value
        else:
            new_sl = entry - beven_value
        new_stage = 1
        logger.info(f"  🛡️ SL STAGE 1: Moving to BREAKEVEN +{BREAKEVEN_PIPS}p → {new_sl:.5f}")
    
    # Stage 1 → 2: 25% toward TP
    elif trade_mgr.sl_stage == 1 and SL_TRAIL_25 and current_profit >= tp_dist * 0.25:
        if direction == "BUY":
            new_sl = entry + tp_dist * 0.25
        else:
            new_sl = entry - tp_dist * 0.25
        new_stage = 2
        logger.info(f"  🛡️ SL STAGE 2: Moving to 25% toward TP → {new_sl:.5f}")
    
    # Stage 2 → 3: 50% toward TP
    elif trade_mgr.sl_stage == 2 and SL_TRAIL_50 and current_profit >= tp_dist * 0.50:
        if direction == "BUY":
            new_sl = entry + tp_dist * 0.50
        else:
            new_sl = entry - tp_dist * 0.50
        new_stage = 3
        logger.info(f"  🛡️ SL STAGE 3: Moving to 50% toward TP → {new_sl:.5f}")
    
    # Stage 3 → 4: 75% toward TP
    elif trade_mgr.sl_stage == 3 and SL_TRAIL_75 and current_profit >= tp_dist * 0.75:
        if direction == "BUY":
            new_sl = entry + tp_dist * 0.75
        else:
            new_sl = entry - tp_dist * 0.75
        new_stage = 4
        logger.info(f"  🛡️ SL STAGE 4: Moving to 75% toward TP → {new_sl:.5f}")
    
    # Apply new SL to all open trades
    if new_sl is not None:
        trades = get_open_trades()
        success_count = 0
        for trade in trades:
            if modify_trade_sl(trade["id"], new_sl):
                success_count += 1
        
        if success_count > 0:
            trade_mgr.current_sl = new_sl
            trade_mgr.sl_stage = new_stage
            logger.info(f"  ✓ SL updated on {success_count}/{len(trades)} trades → Stage: {trade_mgr.get_sl_stage_name()}")


# ============================================================================
# STRATEGY ENGINE — LONDON FORTRESS
# ============================================================================

def analyze_market():
    """
    Perform full London Fortress multi-timeframe analysis.
    Daily: 50 EMA trend filter
    H4: Supertrend + ADX confirmation
    H1: Entry signals (Breakout, EMA Cross, RSI Pullback)
    
    Returns signal dict or None.
    """
    logger.info("═" * 60)
    logger.info(f"  LONDON FORTRESS ANALYSIS — {INSTRUMENT}")
    logger.info(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("═" * 60)
    
    # ── DAILY TREND FILTER (50 EMA) ──
    candles_d = get_candles("D", count=60)
    if len(candles_d) < DAILY_EMA_LEN + 5:
        logger.warning(f"  Not enough Daily data ({len(candles_d)} candles)")
        return None
    
    _, _, _, closes_d, _ = extract_ohlc(candles_d)
    daily_ema = calculate_ema(closes_d, DAILY_EMA_LEN)
    
    current_daily = closes_d[-1]
    daily_ema_val = daily_ema[-1]
    daily_bullish = current_daily > daily_ema_val if daily_ema_val else False
    daily_bearish = current_daily < daily_ema_val if daily_ema_val else False
    
    daily_ema_str = f"{daily_ema_val:.5f}" if daily_ema_val else "N/A"
    trend_str = 'BULLISH ▲' if daily_bullish else ('BEARISH ▼' if daily_bearish else 'NEUTRAL')
    logger.info(f"  DAILY: Price={current_daily:.5f} | 50 EMA={daily_ema_str} | {trend_str}")
    
    # ── H4 SUPERTREND + ADX ──
    candles_h4 = get_candles("H4", count=100)
    if len(candles_h4) < H4_ATR_PERIOD + 10:
        logger.warning(f"  Not enough H4 data ({len(candles_h4)} candles)")
        return None
    
    _, highs_h4, lows_h4, closes_h4, _ = extract_ohlc(candles_h4)
    st_h4, dir_h4 = calculate_supertrend(highs_h4, lows_h4, closes_h4, H4_ATR_PERIOD, H4_ATR_FACTOR)
    adx_h4 = calculate_adx(highs_h4, lows_h4, closes_h4, H4_ADX_LEN)
    
    h4_st_bullish = dir_h4[-1] < 0
    h4_st_bearish = dir_h4[-1] > 0
    h4_st_value = st_h4[-1]
    h4_adx_value = adx_h4[-1] if adx_h4[-1] is not None else 0
    h4_trend_strong = h4_adx_value > H4_ADX_THRESHOLD
    
    h4_st_flip_bull = len(dir_h4) >= 2 and dir_h4[-2] > 0 and dir_h4[-1] < 0
    h4_st_flip_bear = len(dir_h4) >= 2 and dir_h4[-2] < 0 and dir_h4[-1] > 0
    
    h4_st_str = f"{h4_st_value:.5f}" if h4_st_value else "N/A"
    h4_dir_str = 'BULLISH ▲' if h4_st_bullish else 'BEARISH ▼'
    h4_adx_str = 'STRONG' if h4_trend_strong else 'WEAK'
    logger.info(f"  H4 ST: {h4_dir_str} | Value: {h4_st_str} | ADX: {h4_adx_value:.1f} ({h4_adx_str})")
    
    # ── H1 ENTRY SIGNALS ──
    candles_h1 = get_candles("H1", count=100)
    if len(candles_h1) < SLOW_EMA + 10:
        logger.warning(f"  Not enough H1 data ({len(candles_h1)} candles)")
        return None
    
    opens_h1, highs_h1, lows_h1, closes_h1, times_h1 = extract_ohlc(candles_h1)
    
    # H1 EMAs
    fast_ema_h1 = calculate_ema(closes_h1, FAST_EMA)
    slow_ema_h1 = calculate_ema(closes_h1, SLOW_EMA)
    
    ema_bullish = (fast_ema_h1[-1] is not None and slow_ema_h1[-1] is not None 
                   and fast_ema_h1[-1] > slow_ema_h1[-1])
    ema_bearish = (fast_ema_h1[-1] is not None and slow_ema_h1[-1] is not None 
                   and fast_ema_h1[-1] < slow_ema_h1[-1])
    
    # EMA crossover detection
    ema_cross_up = (fast_ema_h1[-2] is not None and slow_ema_h1[-2] is not None and
                    fast_ema_h1[-2] <= slow_ema_h1[-2] and fast_ema_h1[-1] > slow_ema_h1[-1])
    ema_cross_down = (fast_ema_h1[-2] is not None and slow_ema_h1[-2] is not None and
                      fast_ema_h1[-2] >= slow_ema_h1[-2] and fast_ema_h1[-1] < slow_ema_h1[-1])
    
    # H1 RSI
    rsi_h1 = calculate_rsi(closes_h1, RSI_LEN)
    rsi_value = rsi_h1[-1] if rsi_h1[-1] is not None else 50
    rsi_bull_pullback = rsi_value < RSI_BUY_ZONE
    rsi_bear_pullback = rsi_value > RSI_SELL_ZONE
    rsi_rising = (rsi_h1[-1] is not None and rsi_h1[-2] is not None and rsi_h1[-3] is not None and
                  rsi_h1[-1] > rsi_h1[-2] and rsi_h1[-2] < rsi_h1[-3])
    rsi_falling = (rsi_h1[-1] is not None and rsi_h1[-2] is not None and rsi_h1[-3] is not None and
                   rsi_h1[-1] < rsi_h1[-2] and rsi_h1[-2] > rsi_h1[-3])
    
    # H1 Supertrend (for SL reference)
    st_h1, dir_h1 = calculate_supertrend(highs_h1, lows_h1, closes_h1, H4_ATR_PERIOD, H4_ATR_FACTOR)
    h1_st_bullish = dir_h1[-1] < 0
    h1_st_bearish = dir_h1[-1] > 0
    h1_st_flip_bull = len(dir_h1) >= 2 and dir_h1[-2] > 0 and dir_h1[-1] < 0
    h1_st_flip_bear = len(dir_h1) >= 2 and dir_h1[-2] < 0 and dir_h1[-1] > 0
    
    current_price = closes_h1[-1]
    
    ema_dir_str = 'BULLISH ▲' if ema_bullish else 'BEARISH ▼'
    fast_str = f"{fast_ema_h1[-1]:.5f}" if fast_ema_h1[-1] else "N/A"
    slow_str = f"{slow_ema_h1[-1]:.5f}" if slow_ema_h1[-1] else "N/A"
    logger.info(f"  H1 EMA: {ema_dir_str} | 9 EMA: {fast_str} | 21 EMA: {slow_str}")
    logger.info(f"  H1 RSI: {rsi_value:.1f} | ST: {'BULL' if h1_st_bullish else 'BEAR'} | "
                f"Price: {current_price:.5f}")
    
    # ── LONDON BREAKOUT CHECK ──
    update_asian_range()
    breakout = check_breakout()
    if breakout:
        logger.info(f"  BREAKOUT: {breakout} | Asian Range: {asian_range['high']:.5f} / {asian_range['low']:.5f}")
    
    # ══════════════════════════════════════════════════════════════
    # SIGNAL GENERATION
    # ══════════════════════════════════════════════════════════════
    
    signal = None
    
    # --- BUY SIGNALS ---
    # AGGRESSIVE: Allow trades when 2 out of 3 HTF conditions align
    buy_htf_score = sum([daily_bullish, h4_st_bullish, h4_trend_strong])
    buy_htf_aligned = buy_htf_score >= 2  # Was: all 3 required, now: 2 of 3
    buy_htf_full = daily_bullish and h4_st_bullish and h4_trend_strong
    
    # Priority 1: London Breakout (STRONG)
    if buy_htf_aligned and breakout == "LONG_BREAKOUT" and ema_bullish and is_london_session():
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "BREAKOUT", "strength": 3,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "London Breakout + Daily Bull + H4 ST Bull + ADX Strong + EMA Bull"
        }
    
    # Priority 2: H4 Supertrend Flip (STRONG)
    elif buy_htf_aligned and h4_st_flip_bull and ema_bullish:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "ST_FLIP", "strength": 3,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "H4 ST Flip Bull + Daily Bull + ADX Strong + EMA Bull"
        }
    
    # Priority 3: RSI Pullback (MODERATE)
    elif buy_htf_aligned and rsi_bull_pullback and rsi_rising and ema_bullish and current_price > slow_ema_h1[-1]:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "PULLBACK", "strength": 2,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "RSI Pullback Buy + Daily Bull + H4 ST Bull + ADX Strong"
        }
    
    # Priority 4: EMA Cross (MODERATE)
    elif buy_htf_aligned and ema_cross_up and h1_st_bullish:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "EMA_CROSS", "strength": 2,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "EMA 9/21 Cross Up + Daily Bull + H4 ST Bull + ADX Strong"
        }
    
    # Priority 5: Trend Continuation (LIGHT) — AGGRESSIVE: removed session-open-only restriction
    elif buy_htf_aligned and h1_st_bullish and ema_bullish and current_price > fast_ema_h1[-1]:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "TREND_CONT", "strength": 1,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "Trend Continuation + HTF aligned (" + str(buy_htf_score) + "/3)"
        }
    
    # Priority 6: H1 Supertrend Flip with H4 alignment (LIGHT) — AGGRESSIVE: new signal
    elif buy_htf_aligned and h1_st_flip_bull and ema_bullish:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "H1_ST_FLIP", "strength": 1,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "H1 Supertrend Flip Bull + HTF aligned (" + str(buy_htf_score) + "/3)"
        }
    
    # Priority 7: Momentum Breakout — price above Asian high + EMA bull (LIGHT) — AGGRESSIVE: new signal
    elif buy_htf_aligned and asian_range['high'] and current_price > asian_range['high'] and ema_bullish:
        sl = st_h1[-1] - pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price - pips_to_price(50)
        sl_dist = abs(current_price - sl)
        tp = current_price + sl_dist * RISK_REWARD_RATIO
        signal = {
            "direction": "BUY", "type": "MOMENTUM", "strength": 1,
            "entry": current_price, "sl": sl, "tp": tp,
            "reason": "Price above Asian High + EMA Bull + HTF aligned (" + str(buy_htf_score) + "/3)"
        }
    
    # --- SELL SIGNALS ---
    # AGGRESSIVE: Allow trades when 2 out of 3 HTF conditions align
    sell_htf_score = sum([daily_bearish, h4_st_bearish, h4_trend_strong])
    sell_htf_aligned = sell_htf_score >= 2  # Was: all 3 required, now: 2 of 3
    sell_htf_full = daily_bearish and h4_st_bearish and h4_trend_strong
    
    if signal is None:
        # Priority 1: London Breakout Short (STRONG)
        if sell_htf_aligned and breakout == "SHORT_BREAKOUT" and ema_bearish and is_london_session():
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "BREAKOUT", "strength": 3,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "London Breakout Short + Daily Bear + H4 ST Bear + ADX Strong + EMA Bear"
            }
        
        # Priority 2: H4 ST Flip Bear (STRONG)
        elif sell_htf_aligned and h4_st_flip_bear and ema_bearish:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "ST_FLIP", "strength": 3,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "H4 ST Flip Bear + Daily Bear + ADX Strong + EMA Bear"
            }
        
        # Priority 3: RSI Pullback Sell (MODERATE)
        elif sell_htf_aligned and rsi_bear_pullback and rsi_falling and ema_bearish and current_price < slow_ema_h1[-1]:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "PULLBACK", "strength": 2,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "RSI Pullback Sell + Daily Bear + H4 ST Bear + ADX Strong"
            }
        
        # Priority 4: EMA Cross Down (MODERATE)
        elif sell_htf_aligned and ema_cross_down and h1_st_bearish:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "EMA_CROSS", "strength": 2,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "EMA 9/21 Cross Down + Daily Bear + H4 ST Bear + ADX Strong"
            }
        
        # Priority 5: Trend Continuation (LIGHT) — AGGRESSIVE: removed session-open-only restriction
        elif sell_htf_aligned and h1_st_bearish and ema_bearish and current_price < fast_ema_h1[-1]:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "TREND_CONT", "strength": 1,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "Trend Continuation + HTF aligned (" + str(sell_htf_score) + "/3)"
            }
        
        # Priority 6: H1 Supertrend Flip with H4 alignment (LIGHT) — AGGRESSIVE: new signal
        elif sell_htf_aligned and h1_st_flip_bear and ema_bearish:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "H1_ST_FLIP", "strength": 1,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "H1 Supertrend Flip Bear + HTF aligned (" + str(sell_htf_score) + "/3)"
            }
        
        # Priority 7: Momentum Breakdown — price below Asian low + EMA bear (LIGHT) — AGGRESSIVE: new signal
        elif sell_htf_aligned and asian_range['low'] and current_price < asian_range['low'] and ema_bearish:
            sl = st_h1[-1] + pips_to_price(SL_BUFFER_PIPS) if st_h1[-1] else current_price + pips_to_price(50)
            sl_dist = abs(sl - current_price)
            tp = current_price - sl_dist * RISK_REWARD_RATIO
            signal = {
                "direction": "SELL", "type": "MOMENTUM", "strength": 1,
                "entry": current_price, "sl": sl, "tp": tp,
                "reason": "Price below Asian Low + EMA Bear + HTF aligned (" + str(sell_htf_score) + "/3)"
            }
    
    if signal:
        strength_label = {1: "LIGHT", 2: "MODERATE", 3: "STRONG"}
        logger.info(f"  ✓ SIGNAL: {signal['direction']} [{strength_label.get(signal['strength'], '?')}] — {signal['type']}")
        logger.info(f"    Reason: {signal['reason']}")
        logger.info(f"    Entry: {signal['entry']:.5f} | SL: {signal['sl']:.5f} | TP: {signal['tp']:.5f}")
    else:
        logger.info(f"  ○ No signal — conditions not met")
    
    return signal


# ============================================================================
# TRADE EXECUTION ENGINE
# ============================================================================

def process_signal(signal):
    """Process a trading signal: check spread, close opposing, execute stacked trades."""
    if signal is None:
        return
    
    direction = signal["direction"]
    sl = signal["sl"]
    tp = signal["tp"]
    strength = signal.get("strength", 2)
    signal_type = signal.get("type", "UNKNOWN")
    
    # Check spread
    pricing = get_current_price()
    if pricing:
        spread_pips = price_to_pips(pricing["spread"])
        if spread_pips > MAX_SPREAD_PIPS:
            logger.warning(f"  SPREAD TOO HIGH: {spread_pips:.1f} pips > max {MAX_SPREAD_PIPS}")
            return
        logger.info(f"  Spread: {spread_pips:.1f} pips ✓")
    
    # Close opposing positions on strong signals
    if CLOSE_ON_OPPOSITE and strength >= 2:
        existing = get_open_trades()
        for trade in existing:
            trade_units = int(trade.get("currentUnits", 0))
            trade_dir = "BUY" if trade_units > 0 else "SELL"
            if trade_dir != direction:
                logger.info(f"  Closing opposing {trade_dir} trade {trade['id']}")
                close_trade(trade["id"])
    
    # Execute stacked trades
    logger.info(f"  EXECUTING: {direction} | Strength: {strength}/3 | Type: {signal_type}")
    successful = execute_stacked_trades(direction, sl, tp, signal_type, strength)
    
    if successful > 0:
        trade_mgr.daily_trades.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "type": signal_type,
            "strength": strength,
            "entry": signal["entry"],
            "sl": sl,
            "tp": tp,
            "stacks": successful,
            "reason": signal.get("reason", "")
        })


def run_market_scan():
    """Run a complete market scan and execute if signal found."""
    if not is_trading_hours():
        logger.info("  Outside trading hours (8AM-8PM UK), skipping scan")
        return
    
    signal = analyze_market()
    if signal:
        process_signal(signal)
    
    # Always check progressive SL on existing trades
    if trade_mgr.stack_count > 0:
        manage_progressive_sl()
    
    # Log account status
    account = get_account_info()
    if account:
        logger.info(f"  ACCOUNT: Balance={account['balance']:.2f} {account['currency']} | "
                     f"Unrealized P/L={account['unrealized_pl']:.2f} | "
                     f"Open Trades={account['open_trade_count']} | "
                     f"SL Stage: {trade_mgr.get_sl_stage_name()}")


# ============================================================================
# DAILY REPORTING
# ============================================================================

def generate_daily_report():
    """Generate end-of-day trading report."""
    now = datetime.now(timezone.utc)
    report_file = os.path.join(REPORT_DIR, f"london_fortress_{now.strftime('%Y-%m-%d')}.md")
    
    account = get_account_info()
    
    report = f"""# London Fortress — Daily Report
## {now.strftime('%A, %B %d, %Y')}

### Account Summary
| Metric | Value |
|--------|-------|
| Balance | {account['balance']:.2f} {account['currency']} if account else 'N/A' |
| Net P/L Today | {trade_mgr.daily_pnl:.2f} GBP |
| Trades Taken | {len(trade_mgr.daily_trades)} |
| Open Trades | {account['open_trade_count'] if account else 0} |

### Trades Taken Today
"""
    
    if trade_mgr.daily_trades:
        report += "| Time | Direction | Type | Strength | Entry | SL | TP | Stacks |\n"
        report += "|------|-----------|------|----------|-------|----|----|--------|\n"
        for t in trade_mgr.daily_trades:
            report += (f"| {t['time'][:19]} | {t['direction']} | {t['type']} | "
                       f"{t['strength']}/3 | {t['entry']:.5f} | {t['sl']:.5f} | "
                       f"{t['tp']:.5f} | {t['stacks']} |\n")
    else:
        report += "*No trades taken today.*\n"
    
    report += f"\n### Strategy Notes\n"
    report += f"- Trading Hours: {LONDON_OPEN_HOUR}:00 - {TRADING_END_HOUR}:00 UTC\n"
    report += f"- Pair: {INSTRUMENT}\n"
    report += f"- Stack Size: {MAX_STACK_TRADES}x {POSITION_SIZE_PER_STACK} units\n"
    report += f"- R:R Ratio: 1:{RISK_REWARD_RATIO}\n"
    
    try:
        with open(report_file, "w") as f:
            f.write(report)
        logger.info(f"  Daily report saved: {report_file}")
    except Exception as e:
        logger.error(f"  Failed to save report: {e}")
    
    # Reset daily tracking
    trade_mgr.daily_trades = []
    trade_mgr.daily_pnl = 0.0


# ============================================================================
# SCHEDULED EXECUTION
# ============================================================================

def london_open_scan():
    """Execute strategy scan at London Open (8AM UTC)."""
    logger.info("═══ LONDON MARKET OPEN ═══")
    # Reset Asian range for new day
    global asian_range
    asian_range["locked"] = False
    update_asian_range()
    run_market_scan()


def us_open_scan():
    """Execute strategy scan at US Open (1PM UTC)."""
    logger.info("═══ US MARKET OPEN ═══")
    run_market_scan()


def end_of_day():
    """Close all positions and generate report at 8PM UTC."""
    logger.info("═══ END OF DAY ═══")
    if CLOSE_AT_EOD:
        close_all_trades("End of Day 8PM UK")
    generate_daily_report()


def hourly_scan():
    """Periodic scan every 30 minutes during trading hours (AGGRESSIVE)."""
    if not is_trading_hours():
        return
    logger.info("─── 30-MIN SCAN ───")
    run_market_scan()


def sl_check_loop():
    """Check progressive SL every 5 minutes during trading hours."""
    if not is_trading_hours():
        return
    if trade_mgr.stack_count > 0:
        logger.info("─── SL CHECK ───")
        manage_progressive_sl()


# ============================================================================
# FLASK WEBHOOK SERVER
# ============================================================================

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    account = get_account_info()
    return jsonify({
        "status": "healthy",
        "strategy": "London Fortress",
        "pair": INSTRUMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_balance": account["balance"] if account else "N/A",
        "open_trades": trade_mgr.stack_count,
        "sl_stage": trade_mgr.get_sl_stage_name(),
        "trading_hours": is_trading_hours()
    }), 200


@app.route('/status', methods=['GET'])
def status():
    """Get detailed bot status."""
    account = get_account_info()
    trades = get_open_trades()
    return jsonify({
        "status": "running",
        "strategy": "London Fortress",
        "pair": INSTRUMENT,
        "environment": OANDA_ENVIRONMENT,
        "stack_size": f"{MAX_STACK_TRADES}x {POSITION_SIZE_PER_STACK} units",
        "rr_ratio": f"1:{RISK_REWARD_RATIO}",
        "sl_stage": trade_mgr.get_sl_stage_name(),
        "sl_stage_num": trade_mgr.sl_stage,
        "entry_price": trade_mgr.entry_price,
        "current_sl": trade_mgr.current_sl,
        "take_profit": trade_mgr.take_profit,
        "direction": trade_mgr.direction,
        "account": account,
        "open_trades": [
            {
                "id": t["id"],
                "units": t["currentUnits"],
                "unrealized_pl": t.get("unrealizedPL", "0"),
                "open_time": t.get("openTime", "")
            } for t in trades
        ],
        "asian_range": asian_range,
        "daily_trades_count": len(trade_mgr.daily_trades),
        "daily_pnl": trade_mgr.daily_pnl
    }), 200


@app.route('/scan', methods=['POST'])
def manual_scan():
    """Trigger a manual market scan."""
    logger.info("MANUAL SCAN TRIGGERED")
    run_market_scan()
    return jsonify({"status": "scan_complete", "signal": "check_logs"}), 200


@app.route('/close_all', methods=['POST'])
def close_all_endpoint():
    """Close all open positions."""
    logger.info("MANUAL CLOSE ALL TRIGGERED")
    close_all_trades("Manual close via API")
    return jsonify({"status": "all_positions_closed"}), 200


@app.route('/webhook', methods=['POST'])
def webhook_tradingview():
    """
    Receive TradingView webhook alerts.
    Expected JSON format from Pine Script alerts:
    {
        "action": "BUY" | "SELL" | "MODIFY_SL" | "CLOSE_ALL",
        "pair": "GBP_USD",
        "strength": 1-3,
        "type": "BREAKOUT" | "ST_FLIP" | "PULLBACK" | "EMA_CROSS" | "TREND",
        "price": 1.26500,
        "sl": 1.26200,
        "tp": 1.27250,
        "stack": 5,
        "stage": "breakeven" | "25pct" | "50pct" | "75pct",
        "new_sl": 1.26350,
        "reason": "end_of_day"
    }
    """
    try:
        data = request.get_json(force=True)
        logger.info(f"WEBHOOK RECEIVED: {json.dumps(data)}")
        
        action = data.get("action", "").upper()
        pair = data.get("pair", "GBP_USD")
        
        # Validate pair
        if pair.replace("_", "") not in ["GBPUSD", "GBP_USD"]:
            logger.warning(f"  Ignoring webhook for non-GBP/USD pair: {pair}")
            return jsonify({"status": "ignored", "reason": "wrong_pair"}), 200
        
        # --- CLOSE ALL ---
        if action == "CLOSE_ALL":
            reason = data.get("reason", "webhook_signal")
            close_all_trades(f"Webhook: {reason}")
            return jsonify({"status": "closed_all"}), 200
        
        # --- MODIFY SL ---
        elif action == "MODIFY_SL":
            new_sl = data.get("new_sl")
            stage = data.get("stage", "unknown")
            if new_sl:
                trades = get_open_trades()
                modified = 0
                for trade in trades:
                    if modify_trade_sl(trade["id"], float(new_sl)):
                        modified += 1
                
                # Update trade manager
                stage_map = {"breakeven": 1, "25pct": 2, "50pct": 3, "75pct": 4}
                trade_mgr.current_sl = float(new_sl)
                trade_mgr.sl_stage = stage_map.get(stage, trade_mgr.sl_stage)
                
                logger.info(f"  WEBHOOK SL MODIFY: Stage={stage} | New SL={new_sl} | Modified {modified} trades")
                return jsonify({"status": "sl_modified", "modified": modified, "stage": stage}), 200
            else:
                return jsonify({"status": "error", "message": "new_sl required"}), 400
        
        # --- BUY / SELL ---
        elif action in ["BUY", "SELL"]:
            strength = int(data.get("strength", 2))
            signal_type = data.get("type", "WEBHOOK")
            sl = float(data.get("sl", 0))
            tp = float(data.get("tp", 0))
            stack_count = int(data.get("stack", MAX_STACK_TRADES))
            
            # If SL/TP not provided, calculate from current analysis
            if sl == 0 or tp == 0:
                pricing = get_current_price()
                if pricing:
                    current = pricing["mid"]
                    # Use a default 30-pip SL
                    if action == "BUY":
                        sl = current - pips_to_price(30) if sl == 0 else sl
                        tp = current + pips_to_price(30 * RISK_REWARD_RATIO) if tp == 0 else tp
                    else:
                        sl = current + pips_to_price(30) if sl == 0 else sl
                        tp = current - pips_to_price(30 * RISK_REWARD_RATIO) if tp == 0 else tp
            
            # Check spread
            pricing = get_current_price()
            if pricing:
                spread_pips = price_to_pips(pricing["spread"])
                if spread_pips > MAX_SPREAD_PIPS:
                    logger.warning(f"  WEBHOOK: Spread too high ({spread_pips:.1f} pips)")
                    return jsonify({"status": "rejected", "reason": "spread_too_high", "spread": spread_pips}), 200
            
            # Close opposing if strong signal
            if CLOSE_ON_OPPOSITE and strength >= 2:
                existing = get_open_trades()
                for trade in existing:
                    trade_units = int(trade.get("currentUnits", 0))
                    trade_dir = "BUY" if trade_units > 0 else "SELL"
                    if trade_dir != action:
                        close_trade(trade["id"])
            
            # Execute stacked trades
            successful = execute_stacked_trades(action, sl, tp, signal_type, strength)
            
            logger.info(f"  WEBHOOK EXECUTED: {action} | Type: {signal_type} | "
                        f"Strength: {strength}/3 | Stacks: {successful}")
            
            return jsonify({
                "status": "executed",
                "direction": action,
                "type": signal_type,
                "strength": strength,
                "sl": sl,
                "tp": tp,
                "trades_opened": successful
            }), 200
        
        else:
            logger.warning(f"  Unknown webhook action: {action}")
            return jsonify({"status": "unknown_action"}), 400
    
    except Exception as e:
        logger.error(f"  Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# SCHEDULER THREAD
# ============================================================================

def run_scheduler():
    """Run the schedule loop in a background thread."""
    while True:
        schedule.run_pending()
        time.sleep(30)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    logger.info("╔" + "═" * 68 + "╗")
    logger.info("║  LONDON FORTRESS — GBP/USD AUTOMATED TRADING BOT                  ║")
    logger.info("║  Strategy: Multi-TF Trend Following + London Breakout              ║")
    logger.info("║  Account: OANDA LIVE                                               ║")
    logger.info("╚" + "═" * 68 + "╝")
    logger.info(f"  Environment:    {OANDA_ENVIRONMENT.upper()}")
    logger.info(f"  Account:        {OANDA_ACCOUNT_ID}")
    logger.info(f"  Pair:           {INSTRUMENT}")
    logger.info(f"  Stack Size:     {MAX_STACK_TRADES}x {POSITION_SIZE_PER_STACK} units (0.01 lot each)")
    logger.info(f"  R:R Ratio:      1:{RISK_REWARD_RATIO}")
    logger.info(f"  Breakeven:      +{BREAKEVEN_PIPS} pips")
    logger.info(f"  SL Trailing:    25%={SL_TRAIL_25} | 50%={SL_TRAIL_50} | 75%={SL_TRAIL_75}")
    logger.info(f"  Trading Hours:  {LONDON_OPEN_HOUR}:00 - {TRADING_END_HOUR}:00 UTC")
    logger.info(f"  Daily EMA:      {DAILY_EMA_LEN}")
    logger.info(f"  H4 Supertrend:  ATR={H4_ATR_PERIOD}, Factor={H4_ATR_FACTOR}")
    logger.info(f"  H4 ADX:         Len={H4_ADX_LEN}, Threshold={H4_ADX_THRESHOLD}")
    logger.info(f"  H1 EMAs:        {FAST_EMA}/{SLOW_EMA}")
    logger.info(f"  H1 RSI:         Len={RSI_LEN}, Buy<{RSI_BUY_ZONE}, Sell>{RSI_SELL_ZONE}")
    logger.info("─" * 70)
    
    # Verify OANDA connection
    account = get_account_info()
    if account:
        logger.info(f"  ✓ OANDA CONNECTED | Balance: {account['balance']:.2f} {account['currency']} | "
                     f"NAV: {account['nav']:.2f} | Open Trades: {account['open_trade_count']}")
    else:
        logger.error("  ✗ OANDA CONNECTION FAILED — Check API key and account ID")
        logger.error(f"    API Key: {OANDA_API_KEY[:10]}...{OANDA_API_KEY[-10:]}")
        logger.error(f"    Account: {OANDA_ACCOUNT_ID}")
    
    # Schedule market events
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    for day in weekdays:
        getattr(schedule.every(), day).at("08:00").do(london_open_scan)
        getattr(schedule.every(), day).at("13:00").do(us_open_scan)
        getattr(schedule.every(), day).at("20:00").do(end_of_day)
    
    # AGGRESSIVE: Scan every 30 minutes instead of hourly
    schedule.every(30).minutes.do(hourly_scan)
    
    # SL check every 5 minutes
    schedule.every(5).minutes.do(sl_check_loop)
    
    # Run initial scan
    logger.info("Running initial market scan...")
    run_market_scan()
    
    # Start scheduler in background
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start Flask webhook server
    logger.info("Starting webhook server on port 5000...")
    logger.info("Webhook URL: http://<your-server>:5000/webhook")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
