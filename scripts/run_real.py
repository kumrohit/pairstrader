"""Backtest on real crypto data (Coin Metrics community daily reference rates).

Universe: 20 liquid majors. Same walk-forward protocol and cost model as the
synthetic validation; writes results.json for the dashboard.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairstrader.config import PlatformConfig
from pairstrader.data.free_sources import CoinMetricsSource
from pairstrader.backtest.engine import run_backtest
from pairstrader.signals.engines import ZScoreEngine, OUEngine
from pairstrader.performance.metrics import summarize

UNIVERSE = ["btc", "eth", "ltc", "bch", "etc", "xrp", "doge", "ada", "sol",
            "dot", "link", "xlm", "avax", "atom", "uni", "aave", "algo",
            "near", "trx", "fil"]


def main() -> None:
    cfg = PlatformConfig()
    src = CoinMetricsSource(UNIVERSE, start="2022-01-01")
    prices = src.get_prices()
    print(f"Real universe: {len(prices.columns)} assets, "
          f"{prices.index[0].date()} -> {prices.index[-1].date()} ({len(prices)} days)")

    out: dict = {"engines": {}, "universe": list(prices.columns),
                 "source": "Coin Metrics community data (daily USD reference rates)"}
    for engine in (ZScoreEngine(cfg.signal), OUEngine(cfg.signal)):
        result = run_backtest(prices, cfg, engine)
        n_pairs_avg = sum(len(w["pairs_found"]) for w in result.windows) / max(len(result.windows), 1)
        capital = cfg.backtest.capital_per_pair * max(n_pairs_avg, 1.0)
        summary = summarize(result, capital_deployed=round(capital, 0))

        print(f"\n=== engine: {engine.name} ===")
        print(f"windows: {len(result.windows)} | avg pairs/window: {n_pairs_avg:.1f}")
        for w in result.windows:
            print(f"  {w['trading_start']} -> {w['trading_end']}: {w['pairs_found']}")
        print(json.dumps(summary["book"], indent=2))
        print(json.dumps(summary["trades"], indent=2))

        out["engines"][engine.name] = {
            "summary": summary,
            "equity": {str(k.date()): round(float(v), 2) for k, v in result.equity.items()},
            "trades": [asdict(t) for t in result.trades],
            "pair_specs": result.pair_specs,
            "windows": result.windows,
        }

    dest = Path(__file__).resolve().parents[1] / "results.json"
    dest.write_text(json.dumps(out))
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
