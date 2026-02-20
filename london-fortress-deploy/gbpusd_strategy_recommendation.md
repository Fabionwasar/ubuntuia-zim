# GBP/USD Strategy Recommendation: The "London Fortress" System

**Author:** Manus AI
**Date:** February 18, 2026

## 1. Executive Summary

This report outlines a comprehensive, high-potential trading strategy for the **GBP/USD** currency pair, designed to operate exclusively between **8:00 AM and 8:00 PM UK time**. After extensive research into multiple strategies, including the London Breakout, RSI+Supertrend, and various trend-following systems, I recommend a hybrid approach called the **"London Fortress"**. This system combines the capital preservation focus of the "Fortress" strategy [1] with the session-based precision of the London Breakout [2], tailored specifically for GBP/USD.

The London Fortress strategy is designed to be robust, avoid common pitfalls like low-volume chop and counter-trend traps, and capitalize on the unique volatility of the London and New York sessions. It uses a multi-timeframe approach to ensure trades are only taken in the direction of the dominant institutional trend.

## 2. Recommended Strategy: The London Fortress

The London Fortress is a trend-following and breakout strategy that uses a combination of indicators to identify high-probability entries during the London and New York trading sessions. It is designed to be implemented in TradingView Pine Script and executed via webhook alerts.

### 2.1. Core Principles

- **Multi-Timeframe Analysis**: Use the Daily and 4-Hour charts to establish the dominant trend, and the 1-Hour chart for precise entry signals.
- **Session-Based Trading**: Only trade during the London and New York sessions (8:00 AM - 8:00 PM UK time) to capitalize on peak volatility and liquidity.
- **Confluence of Signals**: Require multiple indicators to align before entering a trade, increasing the probability of success.
- **Strict Risk Management**: Employ an ATR-based trailing stop loss to cut losses quickly and protect profits.

### 2.2. Indicator & Timeframe Combination

| Timeframe | Indicator | Purpose |
|---|---|---|
| **Daily** | 50-Day Exponential Moving Average (EMA) | **Institutional Trend Filter**: Determines the overall market direction. Trades are only taken in the direction of this EMA. |
| **4-Hour** | Supertrend (ATR Period: 20, Factor: 3.5) | **Primary Trend Confirmation**: Confirms the trend direction on the H4 timeframe. |
| **4-Hour** | Average Directional Index (ADX) (Length: 14) | **Trend Strength Filter**: Avoids choppy, sideways markets. Trades are only taken when ADX is above 20. |
| **1-Hour** | London Breakout Range | **Entry Trigger**: Uses the high and low of the Asian session (12:00 AM - 8:00 AM UK) as a breakout zone. |
| **1-Hour** | EMA Crossover (9 EMA & 21 EMA) | **Momentum Confirmation**: Confirms the short-term momentum is aligned with the higher timeframe trend. |
| **1-Hour** | Relative Strength Index (RSI) (Length: 14) | **Pullback/Divergence Entry**: Identifies potential pullback entries within a trend. |

### 2.3. Entry Rules

**Long (Buy) Entry:**

1. **Daily Trend Filter**: Price is **above** the Daily 50 EMA.
2. **H4 Trend Confirmation**: 4-Hour Supertrend is **bullish** (green).
3. **H4 Trend Strength**: 4-Hour ADX is **above 20**.
4. **Entry Trigger (choose one):**
   - **London Breakout**: Price breaks **above** the Asian session high during the London session (8:00 AM - 12:00 PM UK).
   - **Pullback Entry**: Price pulls back to the 21 EMA on the 1-Hour chart and RSI shows bullish divergence.
5. **Momentum Confirmation**: 9 EMA is **above** the 21 EMA on the 1-Hour chart.

**Short (Sell) Entry:**

1. **Daily Trend Filter**: Price is **below** the Daily 50 EMA.
2. **H4 Trend Confirmation**: 4-Hour Supertrend is **bearish** (red).
3. **H4 Trend Strength**: 4-Hour ADX is **above 20**.
4. **Entry Trigger (choose one):**
   - **London Breakout**: Price breaks **below** the Asian session low during the London session (8:00 AM - 12:00 PM UK).
   - **Pullback Entry**: Price pulls back to the 21 EMA on the 1-Hour chart and RSI shows bearish divergence.
5. **Momentum Confirmation**: 9 EMA is **below** the 21 EMA on the 1-Hour chart.

### 2.4. Exit Rules

- **Stop Loss**: Initial stop loss is placed at the 4-Hour Supertrend line. An ATR-based trailing stop is then used to lock in profits.
- **Take Profit**: A fixed Risk/Reward ratio of **1:2.5** is recommended, based on the Fortress strategy backtest [1].
- **End of Day Close**: All open positions are closed at **8:00 PM UK time**.

## 3. Rationale for This Strategy

This strategy was chosen for several key reasons:

- **Proven Components**: It combines elements from multiple backtested strategies with a history of profitability on GBP/USD, including the Fortress strategy (+33% profit, 6.7% drawdown) [1] and the London Breakout strategy.
- **Addresses GBP/USD Characteristics**: It is specifically designed to handle the session-based volatility of GBP/USD, avoiding the low-volume Asian session and capitalizing on the London/New York overlap.
- **High-Potential Returns**: The 2.5:1 risk/reward ratio, combined with a ~48% win rate, offers significant profit potential while the strict filtering rules aim to minimize drawdowns.
- **Robust Filtering**: The multi-timeframe and multi-indicator approach provides a strong filter against false signals and choppy market conditions, which is crucial for long-term success.

## 4. Next Steps

1. **Build the Pine Script**: I will now build the complete "London Fortress" strategy in TradingView Pine Script.
2. **Backtest and Optimize**: We will backtest the strategy on historical GBP/USD data to verify its performance and optimize the parameters.
3. **Set Up Webhook Alerts**: Once we are satisfied with the backtest results, we will set up webhook alerts in TradingView for automated execution.
4. **Connect to Middleware**: We will connect the webhooks to a middleware service (e.g., SignalStack) to place trades on your OANDA account.
5. **Demo Trading**: We will run the strategy on your OANDA demo account for at least one week to monitor its live performance before going to live trading.

## 5. References

[1] Thesirrob. (2025). *I backtested 2 years of GBPUSD on the 4H timeframe to see if "Trend Following" still works. Here are the results (Profit Factor 1.48).* Reddit. Retrieved from https://www.reddit.com/r/Forex/comments/1pa8cr8/i_backtested_2_years_of_gbpusd_on_the_4h/

[2] Quantified Strategies. (2025). *London Breakout Strategy: Rules and Backtest Performance*. Retrieved from https://www.quantifiedstrategies.com/london-breakout-strategy/
