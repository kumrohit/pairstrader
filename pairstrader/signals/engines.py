"""Signal engines behind a common interface.

Each engine consumes a spread series (computed with formation-window
hedge ratio, so the trading window is genuinely out-of-sample) and
emits a target position in {-1, 0, +1} spread units:
  +1 = long spread (long y, short beta*x), -1 = short spread.

v1 ships two engines:
  * ZScoreEngine  - rolling z-score bands (Gatev-style, on a cointegrated spread)
  * OUEngine      - fits an OU process on the formation spread and converts
                    the stationary distribution into entry/exit thresholds
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pairstrader.config import SignalConfig


class SignalEngine:
    name: str = "base"

    def positions(self, spread: pd.Series, formation_spread: pd.Series) -> pd.Series:
        raise NotImplementedError  # pragma: no cover


def _band_positions(z: pd.Series, entry: float, exit_: float, stop: float,
                    max_holding: int) -> pd.Series:
    """Stateful band logic shared by both engines: entry at +/-entry,
    exit at |z|<=exit_, hard stop at |z|>=stop, time stop at max_holding.

    The returned Series carries `attrs["exit_reasons"]`, a {bar_index: reason}
    dict with reason in {"converged", "stopped", "timed_out"} for every bar
    on which a position was closed, so the ledger can attribute P&L by exit
    type (the platform's key diagnostic).
    """
    pos = np.zeros(len(z))
    held = 0
    stopped_side = 0  # after a stop, wait for reversion before re-entering same side
    reasons: dict[int, str] = {}
    zv = z.values
    for t in range(1, len(zv)):
        prev = pos[t - 1]
        cur = prev
        if np.isnan(zv[t]):
            pos[t] = 0.0
            continue
        if prev == 0:
            held = 0
            if zv[t] >= entry and stopped_side != -1:
                cur = -1.0   # spread rich: short spread
            elif zv[t] <= -entry and stopped_side != +1:
                cur = +1.0   # spread cheap: long spread
            if abs(zv[t]) < entry:
                stopped_side = 0
        else:
            held += 1
            converged = abs(zv[t]) <= exit_
            stopped = abs(zv[t]) >= stop
            timed_out = held >= max_holding
            if converged or stopped or timed_out:
                stopped_side = int(prev) if stopped else 0
                cur = 0.0
                reasons[t] = ("stopped" if stopped else
                              "converged" if converged else "timed_out")
        pos[t] = cur
    out = pd.Series(pos, index=z.index)
    out.attrs["exit_reasons"] = reasons
    return out


class ZScoreEngine(SignalEngine):
    name = "zscore"

    def __init__(self, cfg: SignalConfig):
        self.cfg = cfg

    def positions(self, spread: pd.Series, formation_spread: pd.Series) -> pd.Series:
        # Rolling stats seeded with formation data so the trading window
        # has a valid z-score from bar one (no warm-up dead zone).
        w = self.cfg.zscore_window
        full = pd.concat([formation_spread.iloc[-w:], spread])
        mu = full.rolling(w).mean()
        sd = full.rolling(w).std(ddof=0)
        z = ((full - mu) / sd).reindex(spread.index)
        return _band_positions(z, self.cfg.entry_z, self.cfg.exit_z,
                               self.cfg.stop_z, self.cfg.max_holding_days)


class OUEngine(SignalEngine):
    """Fit OU params on the formation spread; trade bands in stationary-sigma
    units around the estimated long-run mean. Static thresholds by design:
    parameters are frozen at formation, so the trading window is out-of-sample.
    """
    name = "ou"

    def __init__(self, cfg: SignalConfig, entry_sigmas: float = 1.6):
        self.cfg = cfg
        self.entry_sigmas = entry_sigmas

    @staticmethod
    def fit_ou(s: pd.Series) -> tuple[float, float, float]:
        """Discrete AR(1) -> OU: returns (mu, kappa per bar, stationary sigma)."""
        x = s.dropna().values
        b, a = np.polyfit(x[:-1], np.diff(x), 1)
        kappa = -b
        if kappa <= 1e-6:
            kappa = 1e-6
        mu = a / kappa
        resid = np.diff(x) - (a + b * x[:-1])
        sigma_eps = resid.std(ddof=1)
        sigma_stat = sigma_eps / np.sqrt(kappa * (2.0 - kappa))
        return float(mu), float(kappa), float(max(sigma_stat, 1e-12))

    def positions(self, spread: pd.Series, formation_spread: pd.Series) -> pd.Series:
        mu, _kappa, sigma = self.fit_ou(formation_spread)
        z = (spread - mu) / sigma
        return _band_positions(z, self.entry_sigmas, self.cfg.exit_z,
                               self.cfg.stop_z, self.cfg.max_holding_days)
