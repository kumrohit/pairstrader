"""NSE equities pairs backtest — real data, Rs.15L capital.

Universe: ~55 liquid F&O-eligible names across 10 sectors (static map;
sector classifications drift slowly and this set is stable). Pairs are
restricted to same-sector candidates per the industry-groups evidence.

Capital structure at Rs.15L: capital_per_pair = 3L notional per leg,
max 5 concurrent pairs -> up to 30L gross two-leg exposure. With the
long leg in cash (3L funded) and short leg in futures (~25% margin),
peak deployment is roughly 5 x (3L + 0.75L) = ~18.75L, so a 5-pair book
modestly exceeds 15L; 4 concurrent pairs fits with MTM headroom. The
backtest caps the book at 5 and reports; treat the 5th slot as optional.
LOT-SIZE CAVEAT: single-stock futures trade in lots (SEBI revised
minimum contract values in 2024); a 3L short leg may be below one lot
for high-priced names. The run prints each traded pair's leg notionals —
verify against the current NSE lot-size file before going live.

Windows: 250 formation / 63 trading bars (1y / 1q of trading days),
Sharpe annualized at 252. Both baseline and +stability configs, run once.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairstrader.config import PlatformConfig, india_cash_futures_costs
from pairstrader.data.nse_source import NSEEodSource
from pairstrader.backtest.engine import run_backtest
from pairstrader.signals.engines import ZScoreEngine, OUEngine
from pairstrader.performance.metrics import summarize

SECTORS: dict[str, list[str]] = {
    "BANKS": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
              "BANKBARODA", "PNB", "CANBK", "FEDERALBNK"],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS", "COFORGE"],
    "AUTO": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT",
             "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY"],
    "PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "LUPIN", "AUROPHARMA", "DIVISLAB"],
    "ENERGY": ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL", "HINDPETRO"],
    "METALS": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "SAIL", "JINDALSTEL", "NMDC"],
    "CEMENT": ["ULTRACEMCO", "AMBUJACEM", "ACC", "SHREECEM", "DALBHARAT"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "TATACONSUM"],
    "NBFC": ["BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN"],
    "POWER": ["NTPC", "POWERGRID", "TATAPOWER"],
}
SECTOR_MAP = {sym: sec for sec, syms in SECTORS.items() for sym in syms}
CAPITAL_TOTAL = 1_500_000.0


def make_configs() -> dict[str, PlatformConfig]:
    def base() -> PlatformConfig:
        c = PlatformConfig()
        c.costs = india_cash_futures_costs()
        c.backtest.formation_bars = 250
        c.backtest.trading_bars = 63
        c.backtest.capital_per_pair = 300_000.0
        c.discovery.max_pairs = 5
        return c
    b = base()
    s = base()
    s.discovery.require_stability = True
    s.risk.beta_kill_enabled = True
    return {"": b, "+stability": s}


def main() -> None:
    src = NSEEodSource(list(SECTOR_MAP), start="2019-01-01")
    prices = src.get_prices()
    print(f"NSE universe: {len(prices.columns)} symbols, "
          f"{prices.index[0].date()} -> {prices.index[-1].date()} ({len(prices)} trading days)")

    out: dict = {"engines": {}, "universe": list(prices.columns),
                 "source": "NSE EOD via eod2_data (split/bonus-adjusted), "
                           "sector-restricted, Rs.15L capital"}
    for suffix, cfg in make_configs().items():
        for engine in (ZScoreEngine(cfg.signal), OUEngine(cfg.signal)):
            result = run_backtest(prices, cfg, engine, sector_map=SECTOR_MAP)
            summary = summarize(result, capital_deployed=CAPITAL_TOTAL,
                                bars_per_year=252)
            key = engine.name + "+nse" + suffix

            print(f"\n=== engine: {key} ===")
            npw = sum(len(w["pairs_found"]) for w in result.windows) / max(len(result.windows), 1)
            print(f"windows: {len(result.windows)} | avg pairs/window: {npw:.1f}")
            print(json.dumps(summary["book"], indent=2))
            print(json.dumps(summary["trades"], indent=2))
            print("exit attribution:", {k: (v["count"], round(v["net_pnl"]))
                                        for k, v in summary["exit_attribution"].items()})

            # lot feasibility: short-leg notional per traded pair (latest price)
            seen = {t.pair for t in result.trades}
            lots = {p: f"short-leg ~Rs.{cfg.backtest.capital_per_pair/1e5:.0f}L on "
                       f"{p.split('/')[1]} @ {prices[p.split('/')[1]].iloc[-1]:.0f}"
                    for p in sorted(seen)}
            if lots:
                print("verify against current NSE lot sizes:", list(lots.values())[:5], "...")

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
