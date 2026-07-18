"""Data layer.

A `DataSource` returns a wide DataFrame of close prices indexed by UTC
timestamp, one column per symbol. Adapters for live exchanges (e.g. a
Delta Exchange or Binance client) implement the same interface; the
rest of the platform never touches exchange specifics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class DataSource:
    def get_prices(self) -> pd.DataFrame:  # pragma: no cover - interface
        raise NotImplementedError


class CSVDataSource(DataSource):
    """Loads a wide CSV: first column timestamp, remaining columns = symbols."""

    def __init__(self, path: str):
        self.path = path

    def get_prices(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, parse_dates=[0], index_col=0)
        return df.sort_index().dropna(how="all")


class SyntheticCryptoSource(DataSource):
    """Synthetic daily crypto universe with known cointegration structure.

    Used for platform validation only: several clusters share a common
    stochastic trend (=> genuinely cointegrated members), plus independent
    random walks as negative controls. Ground truth lets us verify the
    discovery engine finds real pairs and rejects fakes.
    """

    def __init__(self, n_days: int = 3 * 365, seed: int = 7):
        self.n_days = n_days
        self.seed = seed

    def get_prices(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.seed)
        idx = pd.date_range("2023-07-01", periods=self.n_days, freq="D", tz="UTC")
        n = self.n_days
        cols: dict[str, np.ndarray] = {}

        # Cluster definitions: (trend vol, members with (name, beta, spread vol, mean-reversion kappa))
        clusters = [
            (0.030, [("BTC", 1.00, 0.000, 0.00),      # anchor
                     ("WBTC", 1.00, 0.004, 0.25),     # tight tracker
                     ("BCH", 0.90, 0.020, 0.08)]),    # looser cousin
            (0.035, [("ETH", 1.00, 0.000, 0.00),
                     ("STETH", 1.00, 0.005, 0.30),
                     ("ETC", 0.85, 0.025, 0.06)]),
            (0.045, [("SOL", 1.00, 0.000, 0.00),
                     ("AVAX", 0.95, 0.022, 0.10),
                     ("NEAR", 0.90, 0.028, 0.07)]),
        ]
        for trend_vol, members in clusters:
            trend = np.cumsum(rng.normal(0.0005, trend_vol, n))
            for name, beta, svol, kappa in members:
                spread = np.zeros(n)
                if svol > 0:
                    eps = rng.normal(0, svol, n)
                    for t in range(1, n):
                        spread[t] = spread[t - 1] * (1 - kappa) + eps[t]
                base = {"BTC": 11.0, "ETH": 8.0, "SOL": 5.0}.get(name, rng.uniform(1.5, 4.0))
                cols[name] = np.exp(base + beta * trend + spread)

        # Negative controls: independent random walks (no cointegration)
        for name, vol in [("DOGE", 0.05), ("XRP", 0.04), ("LINK", 0.045),
                          ("TON", 0.05), ("APT", 0.055), ("UNI", 0.045)]:
            walk = np.cumsum(rng.normal(0.0, vol, n))
            cols[name] = np.exp(rng.uniform(0.5, 3.0) + walk)

        return pd.DataFrame(cols, index=idx)
