"""Walk-forward backtester.

Structure per the literature's standard protocol: a formation window
(pair discovery + hedge ratio + signal calibration) followed by a
non-overlapping trading window, rolled forward through the sample.
Nothing estimated on the trading window is used to trade it.

Cost model (explicit, per Do & Faff's lesson that costs decide viability):
  * fee + slippage bps on every leg, every side (4 executions per round trip)
  * constant annualised funding drag on gross notional while in a position
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pairstrader.config import PlatformConfig
from pairstrader.discovery.pairs import PairSpec, discover_pairs, spread_series
from pairstrader.signals.engines import SignalEngine


@dataclass
class Trade:
    pair: str
    engine: str
    direction: int          # +1 long spread, -1 short spread
    entry_time: str
    exit_time: str
    holding_days: int
    gross_pnl: float
    costs: float
    net_pnl: float
    exit_reason: str        # converged | stopped | timed_out | window_end
    converged: bool


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    daily_pnl: pd.DataFrame          # per-pair net daily pnl
    pair_specs: list[dict] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)


def _pair_window_pnl(prices: pd.DataFrame, spec: PairSpec, pos: pd.Series,
                     cfg: PlatformConfig, engine_name: str,
                     trades: list[Trade]) -> pd.Series:
    """Daily net P&L (currency) for one pair over one trading window.

    Position is expressed in spread units; P&L of one spread unit over a bar
    is notional * (r_y - beta * r_x) with log returns, gross notional sized
    so the two legs sum to capital_per_pair (vol targeting scales it down
    when the formation spread is wild).
    """
    y = np.log(prices[spec.y]).diff()
    x = np.log(prices[spec.x]).diff()
    spread_ret = (y - spec.beta * x).reindex(pos.index).fillna(0.0)

    bt = cfg.backtest
    notional = bt.capital_per_pair

    lag_pos = pos.shift(1).fillna(0.0)
    gross = lag_pos * spread_ret * notional

    # trading costs on position changes: both legs, |delta position|
    delta = pos.diff().abs().fillna(pos.abs())
    per_leg = cfg.costs.one_way_bps / 1e4
    leg_notional = notional * (1.0 + abs(spec.beta)) / (1.0 + abs(spec.beta))  # y + beta*x legs normalised to notional
    exec_costs = delta * 2.0 * per_leg * notional  # 2 legs per spread unit

    # funding drag while holding, on gross two-leg notional
    funding_daily = cfg.costs.funding_annual_pct / 100.0 / 365.0
    funding = lag_pos.abs() * funding_daily * notional * 2.0

    net = gross - exec_costs - funding

    # trade ledger
    in_pos = False
    entry_i = 0
    direction = 0
    g_acc = c_acc = 0.0
    exit_reasons: dict[int, str] = pos.attrs.get("exit_reasons", {})
    pv, gv, ev, fv = pos.values, gross.values, exec_costs.values, funding.values
    idx = pos.index
    for t in range(len(pv)):
        if not in_pos and pv[t] != 0:
            in_pos, entry_i, direction = True, t, int(pv[t])
            g_acc, c_acc = 0.0, ev[t]
        elif in_pos:
            g_acc += gv[t]
            c_acc += ev[t] + fv[t]
            if pv[t] == 0 or t == len(pv) - 1:
                hold = t - entry_i
                if t == len(pv) - 1 and pv[t] != 0:
                    reason = "window_end"
                else:
                    reason = exit_reasons.get(t, "closed")
                trades.append(Trade(
                    pair=spec.name, engine=engine_name, direction=direction,
                    entry_time=str(idx[entry_i].date()), exit_time=str(idx[t].date()),
                    holding_days=hold, gross_pnl=round(g_acc, 2),
                    costs=round(c_acc, 2), net_pnl=round(g_acc - c_acc, 2),
                    exit_reason=reason, converged=(reason == "converged"),
                ))
                in_pos = False
    return net


def run_backtest(prices: pd.DataFrame, cfg: PlatformConfig,
                 engine: SignalEngine) -> BacktestResult:
    bt = cfg.backtest
    n = len(prices)
    trades: list[Trade] = []
    pnl_frames: list[pd.DataFrame] = []
    windows: list[dict] = []
    all_specs: list[dict] = []

    start = 0
    while start + bt.formation_bars + 5 < n:
        f_end = start + bt.formation_bars
        t_end = min(f_end + bt.trading_bars, n)
        form = prices.iloc[start:f_end]
        trade_px = prices.iloc[f_end:t_end]

        specs = discover_pairs(form, cfg.discovery)
        windows.append({
            "formation_start": str(form.index[0].date()),
            "trading_start": str(trade_px.index[0].date()),
            "trading_end": str(trade_px.index[-1].date()),
            "pairs_found": [s.name for s in specs],
        })
        window_pnl: dict[str, pd.Series] = {}
        for spec in specs:
            f_spread = spread_series(form[spec.y], form[spec.x], spec.alpha, spec.beta)
            t_spread = spread_series(trade_px[spec.y], trade_px[spec.x], spec.alpha, spec.beta)
            pos = engine.positions(t_spread, f_spread)
            window_pnl[spec.name] = _pair_window_pnl(trade_px, spec, pos, cfg,
                                                     engine.name, trades)
            all_specs.append({
                "pair": spec.name, "beta": round(spec.beta, 3),
                "adf_pvalue": round(spec.adf_pvalue, 4),
                "half_life_days": round(spec.half_life_days, 1),
                "correlation": round(spec.correlation, 3),
                "window_start": str(trade_px.index[0].date()),
            })
        if window_pnl:
            pnl_frames.append(pd.DataFrame(window_pnl))
        start += bt.trading_bars

    daily = pd.concat(pnl_frames).sort_index() if pnl_frames else pd.DataFrame()
    book = daily.sum(axis=1) if not daily.empty else pd.Series(dtype=float)
    equity = book.cumsum()
    return BacktestResult(equity=equity, trades=trades, daily_pnl=daily,
                          pair_specs=all_specs, windows=windows)
