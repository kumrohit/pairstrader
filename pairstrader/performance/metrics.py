"""Performance tracker.

Reports the measures the literature says matter for pairs books:
risk-adjusted returns AND max drawdown (divergence-risk compensation),
trade-level convergence statistics, and gross-vs-net cost attribution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pairstrader.backtest.engine import BacktestResult

BARS_PER_YEAR = 365  # crypto trades every day


def _sharpe(pnl: pd.Series, capital: float) -> float:
    r = pnl / capital
    if r.std(ddof=1) == 0 or len(r) < 20:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(BARS_PER_YEAR))


def _sortino(pnl: pd.Series, capital: float) -> float:
    r = pnl / capital
    downside = r[r < 0]
    if len(downside) < 5 or downside.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / downside.std(ddof=1) * np.sqrt(BARS_PER_YEAR))


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float((equity - peak).min())


def summarize(result: BacktestResult, capital_deployed: float) -> dict:
    trades = result.trades
    n_trades = len(trades)
    gross = sum(t.gross_pnl for t in trades)
    costs = sum(t.costs for t in trades)
    net = sum(t.net_pnl for t in trades)
    closed = [t for t in trades if t.exit_reason == "closed"]
    winners = [t for t in closed if t.net_pnl > 0]
    book_pnl = result.daily_pnl.sum(axis=1) if not result.daily_pnl.empty else pd.Series(dtype=float)

    per_pair = []
    if not result.daily_pnl.empty:
        for pair in result.daily_pnl.columns:
            p = result.daily_pnl[pair].dropna()
            p_trades = [t for t in trades if t.pair == pair]
            per_pair.append({
                "pair": pair,
                "net_pnl": round(float(p.sum()), 2),
                "gross_pnl": round(sum(t.gross_pnl for t in p_trades), 2),
                "costs": round(sum(t.costs for t in p_trades), 2),
                "trades": len(p_trades),
                "win_rate": round(100 * len([t for t in p_trades if t.net_pnl > 0]) / max(len(p_trades), 1), 1),
                "max_dd": round(_max_drawdown(p.cumsum()), 2),
                "sharpe": round(_sharpe(p, capital_deployed), 2),
            })
        per_pair.sort(key=lambda d: -d["net_pnl"])

    by_reason: dict[str, dict] = {}
    for t in trades:
        r = by_reason.setdefault(t.exit_reason, {"count": 0, "net_pnl": 0.0,
                                                 "gross_pnl": 0.0, "avg_holding_days": 0.0})
        r["count"] += 1
        r["net_pnl"] = round(r["net_pnl"] + t.net_pnl, 2)
        r["gross_pnl"] = round(r["gross_pnl"] + t.gross_pnl, 2)
        r["avg_holding_days"] += t.holding_days
    for r in by_reason.values():
        r["avg_holding_days"] = round(r["avg_holding_days"] / max(r["count"], 1), 1)

    return {
        "exit_attribution": by_reason,
        "book": {
            "net_pnl": round(net, 2),
            "gross_pnl": round(gross, 2),
            "total_costs": round(costs, 2),
            "cost_share_of_gross_pct": round(100 * costs / gross, 1) if gross > 0 else None,
            "sharpe": round(_sharpe(book_pnl, capital_deployed), 2),
            "sortino": round(_sortino(book_pnl, capital_deployed), 2),
            "max_drawdown": round(_max_drawdown(result.equity), 2),
            "return_on_capital_pct": round(100 * net / capital_deployed, 2),
            "capital_deployed": capital_deployed,
        },
        "trades": {
            "count": n_trades,
            "closed": len(closed),
            "win_rate_pct": round(100 * len(winners) / max(len(closed), 1), 1),
            "avg_net_per_trade": round(net / max(n_trades, 1), 2),
            "avg_holding_days": round(np.mean([t.holding_days for t in trades]), 1) if trades else 0,
            "median_holding_days": float(np.median([t.holding_days for t in trades])) if trades else 0,
        },
        "per_pair": per_pair,
    }
