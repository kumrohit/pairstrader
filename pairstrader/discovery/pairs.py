"""Pair discovery engine.

Pipeline (per formation window), following the literature's strongest
selection evidence:
  1. correlation pre-filter on log prices (cheap universe reduction)
  2. Engle-Granger: OLS hedge ratio + ADF test on residual spread
  3. half-life filter via AR(1) on the spread (mean-reversion speed)
  4. rank by ADF p-value, cap book size
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from pairstrader.config import DiscoveryConfig


@dataclass
class PairSpec:
    y: str                 # dependent leg (long spread = long y, short x*beta)
    x: str
    beta: float            # hedge ratio from formation OLS
    alpha: float
    adf_pvalue: float
    half_life_days: float
    correlation: float

    @property
    def name(self) -> str:
        return f"{self.y}/{self.x}"


def hedge_ratio(y: pd.Series, x: pd.Series) -> tuple[float, float]:
    """OLS of log(y) on log(x): returns (alpha, beta)."""
    ly, lx = np.log(y.values), np.log(x.values)
    beta, alpha = np.polyfit(lx, ly, 1)
    return float(alpha), float(beta)


def spread_series(y: pd.Series, x: pd.Series, alpha: float, beta: float) -> pd.Series:
    return np.log(y) - (alpha + beta * np.log(x))


def half_life(spread: pd.Series) -> float:
    """AR(1) half-life in bars: dS_t = a + b*S_{t-1} + e; hl = -ln2/ln(1+b)."""
    s = spread.dropna()
    lag, delta = s.shift(1).iloc[1:], s.diff().iloc[1:]
    b, _a = np.polyfit(lag.values, delta.values, 1)
    if b >= 0:
        return np.inf
    return float(-np.log(2.0) / np.log(1.0 + b))


def discover_pairs(prices: pd.DataFrame, cfg: DiscoveryConfig) -> list[PairSpec]:
    logp = np.log(prices.dropna(axis=1))
    corr = logp.corr()
    found: list[PairSpec] = []

    for a, b in combinations(logp.columns, 2):
        c = corr.loc[a, b]
        if c < cfg.min_correlation:
            continue
        alpha, beta = hedge_ratio(prices[a], prices[b])
        if beta <= 0:
            continue
        spr = spread_series(prices[a], prices[b], alpha, beta)
        try:
            pval = adfuller(spr.values, autolag="AIC")[1]
        except Exception:
            continue
        if pval > cfg.adf_pvalue_max:
            continue
        hl = half_life(spr)
        if not (cfg.half_life_min_days <= hl <= cfg.half_life_max_days):
            continue
        found.append(PairSpec(y=a, x=b, beta=beta, alpha=alpha,
                              adf_pvalue=pval, half_life_days=hl, correlation=float(c)))

    found.sort(key=lambda p: p.adf_pvalue)
    return found[: cfg.max_pairs]
