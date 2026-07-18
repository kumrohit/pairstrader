"""End-to-end validation run on the synthetic universe.

Ground truth: BTC/WBTC, ETH/STETH, SOL/AVAX etc. are cointegrated by
construction; DOGE/XRP/LINK/TON/APT/UNI are independent walks. The run
verifies discovery finds only real pairs, then backtests both engines
and writes results.json for the dashboard.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairstrader.config import PlatformConfig
from pairstrader.data.loader import SyntheticCryptoSource
from pairstrader.backtest.engine import run_backtest
from pairstrader.signals.engines import ZScoreEngine, OUEngine
from pairstrader.performance.metrics import summarize

FAKES = {"DOGE", "XRP", "LINK", "TON", "APT", "UNI"}


def main() -> None:
    cfg = PlatformConfig()
    prices = SyntheticCryptoSource().get_prices()
    print(f"Universe: {len(prices.columns)} symbols x {len(prices)} days")

    out: dict = {"engines": {}, "universe": list(prices.columns)}
    for engine in (ZScoreEngine(cfg.signal), OUEngine(cfg.signal)):
        result = run_backtest(prices, cfg, engine)
        pairs_seen = {s["pair"] for s in result.pair_specs}
        false_pos = [p for p in pairs_seen if any(leg in FAKES for leg in p.split("/"))]
        n_pairs_avg = sum(len(w["pairs_found"]) for w in result.windows) / max(len(result.windows), 1)
        capital = cfg.backtest.capital_per_pair * max(n_pairs_avg, 1.0)
        summary = summarize(result, capital_deployed=round(capital, 0))

        print(f"\n=== engine: {engine.name} ===")
        print(f"windows: {len(result.windows)} | distinct pairs: {len(pairs_seen)} | "
              f"false positives vs ground truth: {len(false_pos)} {false_pos}")
        print(json.dumps(summary["book"], indent=2))
        print(json.dumps(summary["trades"], indent=2))

        out["engines"][engine.name] = {
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
    dest.write_text(json.dumps(out))
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
