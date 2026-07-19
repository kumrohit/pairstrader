"""NSE EOD data adapter.

Source: github.com/BennyThadikaran/eod2_data — daily bhavcopy-derived OHLCV
per symbol since 1995, adjusted for splits and bonuses (essential for
cointegration work: an unadjusted 1:5 split looks exactly like a
catastrophic spread divergence). Updated daily upstream; cached locally
for 24h. Free, keyless, reachable over raw.githubusercontent.com.

Symbols are NSE tickers; files are lowercase (M&M -> "m&m.csv", URL-encoded).
Missing or thin-history symbols are dropped with a warning, same policy as
CoinMetricsSource.
"""
from __future__ import annotations

import io
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from pairstrader.data.loader import DataSource

_UA = {"User-Agent": "pairstrader/0.1 (research)"}


class NSEEodSource(DataSource):
    BASE = "https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/{fname}"

    def __init__(self, symbols: list[str], start: str = "2019-01-01",
                 end: str | None = None, cache_dir: str = ".data_cache",
                 min_coverage: float = 0.95, align: str = "strict"):
        """align="strict": drop thin symbols and any row with a gap (survivor
        panel, original behavior). align="ragged": keep everything, NaNs and
        all — required for point-in-time universes that include names which
        crash, thin out, or stop trading mid-sample."""
        self.symbols = symbols
        self.start, self.end = start, end
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.min_coverage = min_coverage
        self.align = align

    def _one(self, symbol: str) -> pd.Series | None:
        safe = symbol.lower().replace("/", "-")
        cached = self.cache / f"nse_{safe.replace('&', '_and_')}.csv"
        if cached.exists() and time.time() - cached.stat().st_mtime < 86_400:
            raw = cached.read_bytes()
        else:
            url = self.BASE.format(fname=urllib.parse.quote(f"{safe}.csv"))
            try:
                req = urllib.request.Request(url, headers=_UA)
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
            except Exception as exc:  # 404s for renamed/delisted symbols
                print(f"[NSEEodSource] {symbol}: fetch failed ({exc}) — dropped")
                return None
            cached.write_bytes(raw)
        df = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"],
                         usecols=["Date", "Close", "Volume"])
        df = df[~df["Date"].duplicated(keep="last")].set_index("Date").sort_index()
        s = df["Close"].astype(float)
        s.name = symbol
        self._volumes[symbol] = df["Volume"].astype(float)
        return s

    def get_prices(self) -> pd.DataFrame:
        self._volumes: dict[str, pd.Series] = {}
        series = [x for x in (self._one(sym) for sym in self.symbols) if x is not None]
        df = pd.concat(series, axis=1).sort_index()
        df.index = df.index.tz_localize("UTC")
        df = df.loc[self.start: self.end]
        if self.align == "ragged":
            return df
        coverage = df.notna().mean()
        thin = coverage[coverage < self.min_coverage]
        if len(thin):
            print(f"[NSEEodSource] dropping thin-history symbols: "
                  f"{', '.join(f'{a} ({c:.0%})' for a, c in thin.items())}")
            df = df[coverage[coverage >= self.min_coverage].index]
        return df.dropna(how="any")

    def get_volumes(self) -> pd.DataFrame:
        """Volumes aligned to the last get_prices() call (call that first)."""
        df = pd.concat(self._volumes, axis=1).sort_index()
        df.index = df.index.tz_localize("UTC")
        return df.loc[self.start: self.end]
