"""
Telegram Notification Module for London Fortress Bot
=====================================================
Sends real-time alerts to Telegram when:
- New trades are opened
- SL stages change
- Daily reports are generated
- Errors occur

Setup:
1. Create a Telegram bot via @BotFather
2. Get your chat_id by messaging @userinfobot
3. Set environment variables: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
"""

import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger("TelegramNotifier")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

if not TELEGRAM_ENABLED:
    logger.warning("Telegram notifications disabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable.")


def send_telegram_message(message: str, parse_mode: str = None) -> bool:
    """
    Send a message to Telegram.
    
    Args:
        message: The message text (supports HTML formatting)
        parse_mode: Message formatting mode (HTML or Markdown)
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not TELEGRAM_ENABLED:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Telegram message sent successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def notify_trade_opened(direction: str, entry_price: float, sl: float, tp: float, stack_count: int, balance: float):
    """Send notification when a new trade is opened."""
    emoji = "🟢" if direction == "BUY" else "🔴"
    message = f"""
{emoji} <b>TRADE OPENED</b>

<b>Direction:</b> {direction}
<b>Entry Price:</b> {entry_price:.5f}
<b>Stop Loss:</b> {sl:.5f}
<b>Take Profit:</b> {tp:.5f}
<b>Stack Size:</b> {stack_count}x 100 units
<b>Account Balance:</b> £{balance:.2f}

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


def notify_sl_stage_change(old_stage: str, new_stage: str, new_sl: float, unrealized_pl: float):
    """Send notification when SL stage changes."""
    message = f"""
🛡️ <b>STOP LOSS UPDATED</b>

<b>Stage:</b> {old_stage} → {new_stage}
<b>New SL:</b> {new_sl:.5f}
<b>Unrealized P/L:</b> £{unrealized_pl:.2f}

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


def notify_trade_closed(direction: str, entry_price: float, exit_price: float, pnl: float, reason: str, balance: float):
    """Send notification when a trade is closed."""
    emoji = "✅" if pnl >= 0 else "❌"
    pnl_emoji = "💰" if pnl >= 0 else "📉"
    message = f"""
{emoji} <b>TRADE CLOSED</b>

<b>Direction:</b> {direction}
<b>Entry:</b> {entry_price:.5f}
<b>Exit:</b> {exit_price:.5f}
<b>P/L:</b> {pnl_emoji} £{pnl:.2f}
<b>Reason:</b> {reason}
<b>Account Balance:</b> £{balance:.2f}

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


def notify_daily_report(date: str, trades_count: int, total_pnl: float, win_rate: float, balance: float):
    """Send daily trading report."""
    emoji = "📊"
    pnl_emoji = "💰" if total_pnl >= 0 else "📉"
    message = f"""
{emoji} <b>DAILY REPORT</b>

<b>Date:</b> {date}
<b>Trades Taken:</b> {trades_count}
<b>Total P/L:</b> {pnl_emoji} £{total_pnl:.2f}
<b>Win Rate:</b> {win_rate:.1f}%
<b>Account Balance:</b> £{balance:.2f}

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


def notify_error(error_message: str):
    """Send error notification."""
    message = f"""
⚠️ <b>BOT ERROR</b>

<b>Error:</b> {error_message}

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


def notify_bot_started(balance: float, environment: str):
    """Send notification when bot starts."""
    message = f"""
🚀 BOT STARTED

Environment: {environment.upper()}
Account Balance: £{balance:.2f}
Strategy: London Fortress v2 AGGRESSIVE
Pair: GBP/USD

London Fortress Bot
{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
    send_telegram_message(message.strip())


def notify_bot_stopped():
    """Send notification when bot stops."""
    message = f"""
🛑 <b>BOT STOPPED</b>

<i>London Fortress Bot</i>
<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
    send_telegram_message(message.strip())


if __name__ == "__main__":
    # Test notifications
    print("Testing Telegram notifications...")
    if TELEGRAM_ENABLED:
        send_telegram_message("🧪 <b>Test Message</b>\n\nTelegram notifications are working!")
        print("Test message sent. Check your Telegram.")
    else:
        print("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.")
