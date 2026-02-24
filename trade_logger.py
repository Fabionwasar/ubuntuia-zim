"""
Trade Logger Module
===================
Logs trades to the Manus website database via tRPC API
"""

import requests
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# Website API endpoint
WEBSITE_API_URL = "https://3000-ie9n2bd4b7ji881vh05px-7d8d9410.us1.manus.computer/api/trpc/trades.logTrade"
WEBSITE_UPDATE_URL = "https://3000-ie9n2bd4b7ji881vh05px-7d8d9410.us1.manus.computer/api/trpc/trades.updateTrade"

logger = logging.getLogger(__name__)

def log_trade_opened(
    bot: str,  # 'fortress' or 'mean-reversion'
    pair: str,
    direction: str,  # 'BUY' or 'SELL'
    signal_type: str,
    entry_price: float,
    units: int,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """
    Log a newly opened trade to the database
    Returns the trade ID if successful, None otherwise
    """
    try:
        payload = {
            "bot": bot,
            "pair": pair,
            "direction": direction,
            "signalType": signal_type,
            "entryPrice": str(entry_price),
            "units": units,
            "stopLoss": str(stop_loss) if stop_loss else None,
            "takeProfit": str(take_profit) if take_profit else None,
            "status": "open",
            "openedAt": datetime.utcnow().isoformat() + "Z",
            "metadata": str(metadata) if metadata else None,
        }

        response = requests.post(
            WEBSITE_API_URL,
            json={"json": payload},
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("result", {}).get("data", {}).get("json", {}).get("success"):
                trade_id = result["result"]["data"]["json"]["tradeId"]
                logger.info(f"✓ Trade logged to database (ID: {trade_id})")
                return trade_id
            else:
                logger.warning(f"Failed to log trade: {result}")
                return None
        else:
            logger.warning(f"Failed to log trade (HTTP {response.status_code}): {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error logging trade to database: {e}")
        return None


def log_trade_closed(
    trade_id: int,
    exit_price: float,
    pnl: float
) -> bool:
    """
    Update a trade when it's closed
    Returns True if successful, False otherwise
    """
    try:
        payload = {
            "tradeId": trade_id,
            "exitPrice": str(exit_price),
            "pnl": str(pnl),
            "status": "closed",
            "closedAt": datetime.utcnow().isoformat() + "Z",
        }

        response = requests.post(
            WEBSITE_UPDATE_URL,
            json={"json": payload},
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("result", {}).get("data", {}).get("json", {}).get("success"):
                logger.info(f"✓ Trade {trade_id} updated in database (P/L: {pnl})")
                return True
            else:
                logger.warning(f"Failed to update trade: {result}")
                return False
        else:
            logger.warning(f"Failed to update trade (HTTP {response.status_code}): {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error updating trade in database: {e}")
        return False
