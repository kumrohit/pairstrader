"""Backtest on economically-linked pairs (Binance klines).

Universe: WBTC/BTC and WBETH/ETH — a wrapped token and its underlying, and
Binance's own liquid-staking wrapper and its underlying. Unlike the majors
universe (independent large-caps that only look cointegrated by chance in
some formation windows), these pairs have a *structural* reason to stay
tied together. See STRATEGY.md §8b for the motivation.

History is short: WBETHUSDT only lists from 2023-07-19, so the common
window across all four symbols runs from mid-2023 to today (~3 years,
~8 walk-forward windows at the platform's 365/90-day protocol) versus the
majors' 14 windows. Small sample — treat accordingly.

Writes into the same results.json the majors backtest uses (merge-safe:
reads any existing file and only overwrites its own engine keys), so the
dashboard's engine toggle picks up "zscore+linked"/"ou+linked" with no
dashboard changes.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairstrader.config import PlatformConfig
from pairstrader.data.free_sources import BinanceSource
from pairstrader.backtest.engine import run_backtest
from pairstrader.signals.engines import ZScoreEngine, OUEngine
from pairstrader.performance.metrics import summarize

SYMBOL_TO_ASSET = {"BTCUSDT": "BTC", "WBTCUSDT": "WBTC",
                    "ETHUSDT": "ETH", "WBETHUSDT": "WBETH"}


def main() -> None:
    src = BinanceSource(list(SYMBOL_TO_ASSET), interval="1d", start="2023-06-01")
    prices = src.get_prices().rename(columns=SYMBOL_TO_ASSET)
    print(f"Linked-pairs universe: {len(prices.columns)} assets, "
          f"{prices.index[0].date()} -> {prices.index[-1].date()} ({len(prices)} days)")

    cfg = PlatformConfig()
    out: dict = {"engines": {}, "universe": list(prices.columns),
                 "source": "Binance public klines (WBTC/BTC, WBETH/ETH)"}

    for engine in (ZScoreEngine(cfg.signal), OUEngine(cfg.signal)):
        result = run_backtest(prices, cfg, engine)
        n_pairs_avg = sum(len(w["pairs_found"]) for w in result.windows) / max(len(result.windows), 1)
        capital = cfg.backtest.capital_per_pair * max(n_pairs_avg, 1.0)
        summary = summarize(result, capital_deployed=round(capital, 0))
        key = engine.name + "+linked"

        print(f"\n=== engine: {key} ===")
        print(f"windows: {len(result.windows)} | avg pairs/window: {n_pairs_avg:.1f}")
        for w in result.windows:
            print(f"  {w['trading_start']} -> {w['trading_end']}: {w['pairs_found']}")
        print(json.dumps(summary["book"], indent=2))
        print(json.dumps(summary["trades"], indent=2))

        out["engines"][key] = {
            "summary": summary,
            "equity": {str(k.date()): round(float(v), 2) for k, v in result.equity.items()},
            "trades": [asdict(t) for t in result.trades],
            "pair_equity": {c: {str(k.date()): round(float(v), 2)
                                for k, v in result.daily_pnl[c].dropna().cumsum().items()}
                            for c in (result.daily_pnl.columns if not result.daily_pnl.empty else [])},
            "pair_specs": result.pair_specs,
            "windows": result.windows,
        }

    dest = Path(__file__).resolve().parents[1] / "results.json"
    if dest.exists():
        prior = json.loads(dest.read_text())
        out["engines"] = {**prior.get("engines", {}), **out["engines"]}
    dest.write_text(json.dumps(out))
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
