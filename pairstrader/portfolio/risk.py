"""Trading-window risk overlays.

`beta_drift_kill` re-estimates the hedge ratio on a rolling window during
the trading period (seeded with the formation tail so bar one is valid).
If the rolling beta walks more than `tol` away from the frozen formation
beta, the relationship is presumed broken: the position is force-closed
(exit reason "beta_break") and the pair is locked out for the remainder
of the trading window. This is the trading-time counterpart of the
formation-time stability check.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pairstrader.config import RiskConfig
from pairstrader.discovery.pairs import PairSpec


def _rolling_beta(ly: pd.Series, lx: pd.Series, window: int) -> pd.Series:
    cov = ly.rolling(window).cov(lx)
    var = lx.rolling(window).var()
    return cov / var


def beta_drift_kill(pos: pd.Series, form: pd.DataFrame, trade_px: pd.DataFrame,
                    spec: PairSpec, cfg: RiskConfig) -> pd.Series:
    """Return positions with the beta-break kill applied. Preserves and
    extends `pos.attrs["exit_reasons"]`."""
    w = cfg.beta_kill_window
    ly = np.log(pd.concat([form[spec.y].iloc[-w:], trade_px[spec.y]]))
    lx = np.log(pd.concat([form[spec.x].iloc[-w:], trade_px[spec.x]]))
    beta_t = _rolling_beta(ly, lx, w).reindex(pos.index)
    breach = (beta_t / spec.beta - 1.0).abs() > cfg.beta_kill_tol

    if not breach.any():
        return pos

    t0 = int(np.argmax(breach.values))          # first breach bar
    reasons = dict(pos.attrs.get("exit_reasons", {}))
    new = pos.copy()
    new.iloc[t0:] = 0.0
    if pos.iloc[t0 - 1] != 0 if t0 > 0 else False:
        reasons[t0] = "beta_break"
        # drop any reason the engine recorded after the kill bar
        reasons = {k: v for k, v in reasons.items() if k <= t0}
    else:
        reasons = {k: v for k, v in reasons.items() if k < t0}
    out = pd.Series(new.values, index=pos.index)
    out.attrs["exit_reasons"] = reasons
    return out
