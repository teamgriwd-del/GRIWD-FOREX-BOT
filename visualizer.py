"""
Trade Visualizer
Plots equity curve, trade distribution, win/loss stats, and price chart
with entry/exit markers. Uses matplotlib (no external broker dependency).
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd
import numpy as np
from typing import Optional


def plot_equity_curve(equity_curve: list, title: str = "Equity Curve"):
    if not equity_curve:
        print("No equity data to plot.")
        return
    df = pd.DataFrame(equity_curve).set_index("timestamp")
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(df.index, df["equity"], color="#00C896", linewidth=1.5, label="Equity")
    ax.fill_between(df.index, df["equity"].min(), df["equity"],
                    alpha=0.15, color="#00C896")
    ax.axhline(df["equity"].iloc[0], color="gray", linestyle="--", linewidth=0.8,
               label="Starting Balance")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("Balance (USD)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig("equity_curve.png", dpi=150)
    plt.show()
    print("Equity curve saved to equity_curve.png")


def plot_trade_distribution(closed_trades: list):
    if not closed_trades:
        print("No closed trades to plot.")
        return
    pnls = [t.pnl for t in closed_trades]
    wins  = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("CTCFx Bot — Trade Analysis", fontsize=14, fontweight="bold")

    # PnL distribution
    axes[0].hist(pnls, bins=30, color="#5B9BD5", edgecolor="white", linewidth=0.5)
    axes[0].axvline(0, color="red", linewidth=1.2, linestyle="--")
    axes[0].set_title("PnL Distribution")
    axes[0].set_xlabel("PnL (USD)")
    axes[0].set_ylabel("Frequency")

    # Win / Loss breakdown
    categories  = ["Wins", "Losses"]
    counts      = [len(wins), len(losses)]
    bar_colors  = ["#00C896", "#E74C3C"]
    axes[1].bar(categories, counts, color=bar_colors, width=0.5, edgecolor="white")
    axes[1].set_title("Win / Loss Count")
    axes[1].set_ylabel("Number of Trades")
    for bar, count in zip(axes[1].patches, counts):
        axes[1].text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + 0.3, str(count),
                     ha="center", va="bottom", fontweight="bold")

    # Cumulative PnL
    cum_pnl = pd.Series(pnls).cumsum()
    axes[2].plot(cum_pnl.values, color="#9B59B6", linewidth=1.5)
    axes[2].axhline(0, color="gray", linestyle="--", linewidth=0.8)
    axes[2].fill_between(range(len(cum_pnl)), 0, cum_pnl.values,
                          where=cum_pnl.values >= 0, alpha=0.2, color="#00C896")
    axes[2].fill_between(range(len(cum_pnl)), 0, cum_pnl.values,
                          where=cum_pnl.values < 0,  alpha=0.2, color="#E74C3C")
    axes[2].set_title("Cumulative PnL")
    axes[2].set_xlabel("Trade #")
    axes[2].set_ylabel("USD")

    plt.tight_layout()
    plt.savefig("trade_analysis.png", dpi=150)
    plt.show()
    print("Trade analysis saved to trade_analysis.png")


def plot_price_with_trades(df_5m: pd.DataFrame, closed_trades: list,
                           n_candles: int = 500):
    """Candlestick chart with entry/exit markers for last n_candles."""
    df = df_5m.iloc[-n_candles:].copy()
    if df.empty:
        print("No price data to plot.")
        return

    fig, ax = plt.subplots(figsize=(18, 7))

    # Draw simplified OHLC bars
    for i, (ts, row) in enumerate(df.iterrows()):
        color = "#00C896" if row["close"] >= row["open"] else "#E74C3C"
        # Body
        body_bottom = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        ax.bar(i, body_height, bottom=body_bottom,
               color=color, width=0.6, edgecolor="none")
        # Wicks
        ax.plot([i, i], [row["low"], body_bottom], color=color, linewidth=0.7)
        ax.plot([i, i], [body_bottom + body_height, row["high"]],
                color=color, linewidth=0.7)

    # Overlay trades
    start_ts = df.index[0]
    end_ts   = df.index[-1]
    for trade in closed_trades:
        if trade.open_time < start_ts or trade.open_time > end_ts:
            continue
        try:
            entry_i = df.index.get_loc(trade.open_time, method="nearest")
            close_i = df.index.get_loc(trade.close_time, method="nearest")
        except Exception:
            continue
        color = "#00C896" if trade.direction == "buy" else "#E74C3C"
        marker = "^" if trade.direction == "buy" else "v"
        ax.plot(entry_i, trade.entry, marker=marker, color=color,
                markersize=9, zorder=5)
        ax.plot(close_i, trade.close_price, marker="x", color="white",
                markersize=8, markeredgewidth=2, zorder=5)
        ax.annotate("", xy=(close_i, trade.close_price),
                    xytext=(entry_i, trade.entry),
                    arrowprops=dict(arrowstyle="-", color=color, alpha=0.4,
                                   linewidth=1.2))

    buy_patch  = mpatches.Patch(color="#00C896", label="Buy Entry")
    sell_patch = mpatches.Patch(color="#E74C3C", label="Sell Entry")
    ax.legend(handles=[buy_patch, sell_patch])
    ax.set_title(f"CTCFx Bot — Price Chart (last {n_candles} candles)", fontsize=13)
    ax.set_xlabel("Bar Index")
    ax.set_ylabel("Price")
    ax.grid(alpha=0.2)
    plt.tight_layout()
    plt.savefig("price_chart.png", dpi=150)
    plt.show()
    print("Price chart saved to price_chart.png")


def run_all_charts(stats: dict, rm, df_5m: pd.DataFrame):
    plot_equity_curve(stats.get("equity_curve", []),
                      title="CTCFx Synthetic Bot — Equity Curve")
    plot_trade_distribution(rm.closed_trades)
    plot_price_with_trades(df_5m, rm.closed_trades)
