"""Free data adapters.

Two zero-cost sources, both behind the same `DataSource` interface:

* CoinMetricsSource - Coin Metrics "community data", published as per-asset
  daily CSVs on GitHub (github.com/coinmetrics/data). Reputable reference
  rates, full history from genesis, no key, no rate limits. Daily bars only.

* BinanceSource - Binance public klines REST endpoint. Keyless for market
  data, full per-venue history, intraday granularity, paginated at 1000
  candles per request. Use this on your own machine when you want hourly
  bars or exchange-exact prices; respect the (generous) IP rate limits.

Both cache to local parquet/CSV so repeated backtests don't re-download.
"""
from __future__ import annotations

import io
import time
import urllib.request
from pathlib import Path

import pandas as pd

from pairstrader.data.loader import DataSource

_UA = {"User-Agent": "pairstrader/0.1 (research)"}


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class CoinMetricsSource(DataSource):
    """Daily USD reference prices from Coin Metrics community data (GitHub)."""

    BASE = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{asset}.csv"

    def __init__(self, assets: list[str], start: str = "2021-01-01",
                 end: str | None = None, cache_dir: str = ".data_cache"):
        self.assets = [a.lower() for a in assets]
        self.start, self.end = start, end
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)

    def _one(self, asset: str) -> pd.Series:
        cached = self.cache / f"cm_{asset}.csv"
        if cached.exists() and time.time() - cached.stat().st_mtime < 86_400:
            raw = cached.read_bytes()
        else:
            raw = _http_get(self.BASE.format(asset=asset))
            cached.write_bytes(raw)
        df = pd.read_csv(io.BytesIO(raw), usecols=lambda c: c in
                         ("time", "PriceUSD", "ReferenceRateUSD"),
                         parse_dates=["time"])
        px = df.set_index("time")
        col = "ReferenceRateUSD" if "ReferenceRateUSD" in px.columns else "PriceUSD"
        s = px[col].astype(float)
        if col == "ReferenceRateUSD" and "PriceUSD" in px.columns:
            s = s.fillna(px["PriceUSD"].astype(float))
        s.name = asset.upper()
        return s

    def get_prices(self) -> pd.DataFrame:
        series = [self._one(a) for a in self.assets]
        df = pd.concat(series, axis=1).sort_index()
        df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index
        df = df.loc[self.start: self.end]
        # Community tier carries full history only for some assets; drop any
        # column covering <90% of the window rather than truncating the panel.
        coverage = df.notna().mean()
        dropped = coverage[coverage < 0.90]
        if len(dropped):
            print(f"[CoinMetricsSource] dropping thin-history assets: "
                  f"{', '.join(f'{a} ({c:.0%})' for a, c in dropped.items())}")
            df = df[coverage[coverage >= 0.90].index]
        return df.dropna(how="any")


class BinanceSource(DataSource):
    """Keyless Binance spot klines. Symbols like 'BTCUSDT'; interval '1d'/'1h'."""

    BASE = ("https://api.binance.com/api/v3/klines?symbol={sym}"
            "&interval={iv}&startTime={start}&limit=1000")

    def __init__(self, symbols: list[str], interval: str = "1d",
                 start: str = "2021-01-01", cache_dir: str = ".data_cache",
                 pause_s: float = 0.25):
        self.symbols, self.interval, self.start = symbols, interval, start
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.pause_s = pause_s

    def _one(self, sym: str) -> pd.Series:
        import json
        cached = self.cache / f"bn_{sym}_{self.interval}.csv"
        if cached.exists() and time.time() - cached.stat().st_mtime < 86_400:
            s = pd.read_csv(cached, parse_dates=["time"], index_col="time")["close"]
            s.name = sym
            return s
        start_ms = int(pd.Timestamp(self.start, tz="UTC").timestamp() * 1000)
        rows: list[tuple] = []
        while True:
            url = self.BASE.format(sym=sym, iv=self.interval, start=start_ms)
            batch = json.loads(_http_get(url))
            if not batch:
                break
            rows += [(int(k[0]), float(k[4])) for k in batch]  # open time, close
            if len(batch) < 1000:
                break
            start_ms = batch[-1][0] + 1
            time.sleep(self.pause_s)
        s = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC"): c for t, c in rows},
                      name=sym)
        s.rename_axis("time").to_frame("close").to_csv(cached)
        return s

    def get_prices(self) -> pd.DataFrame:
        return pd.concat([self._one(s) for s in self.symbols], axis=1)\
                 .sort_index().dropna(how="any")
