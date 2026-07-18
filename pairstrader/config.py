"""Central configuration for the pairs trading platform.

All economically meaningful assumptions live here so the backtest is
auditable in one place. Defaults are conservative and sized for crypto
perpetual futures (fee-per-leg, slippage, funding carry).
"""
from dataclasses import dataclass, field


@dataclass
class CostConfig:
    """Explicit cost model. Applied per leg, per side, on notional."""
    taker_fee_bps: float = 5.0        # exchange taker fee per leg
    slippage_bps: float = 3.0         # assumed impact/slippage per leg
    funding_annual_pct: float = 8.0   # net annualised funding drag on gross notional
                                      # (conservative: assume carry works against us)

    @property
    def one_way_bps(self) -> float:
        return self.taker_fee_bps + self.slippage_bps


@dataclass
class DiscoveryConfig:
    """Pair discovery filters, applied on the formation window."""
    min_correlation: float = 0.80     # log-price correlation pre-filter
    adf_pvalue_max: float = 0.05      # Engle-Granger residual ADF threshold
    half_life_min_days: float = 1.0   # too fast = microstructure noise
    half_life_max_days: float = 30.0  # too slow = capital tied up, break risk
    max_pairs: int = 10               # book size cap
    # Stability requirement: the relationship must hold on formation
    # sub-windows, not just the full window. Parameters fixed a priori
    # (literature-standard), not tuned on our sample.
    require_stability: bool = False
    stability_subwindows: int = 3     # split formation into K segments
    stability_half_life_max_days: float = 45.0  # per-segment mean reversion must exist
    stability_beta_drift_max: float = 0.25  # max |beta_seg/beta_full - 1|


@dataclass
class RiskConfig:
    """Trading-window risk overlays."""
    beta_kill_enabled: bool = False
    beta_kill_window: int = 60        # bars for rolling beta re-estimate
    beta_kill_tol: float = 0.30       # kill pair if |beta_t/beta_form - 1| exceeds


@dataclass
class SignalConfig:
    """Z-score signal engine parameters."""
    zscore_window: int = 60           # rolling window (bars) for spread z-score
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 3.5               # divergence stop
    max_holding_days: int = 45        # time stop: exit unconverged trades


@dataclass
class BacktestConfig:
    """Walk-forward windows (in bars; daily bars => days)."""
    formation_bars: int = 365
    trading_bars: int = 90
    capital_per_pair: float = 10_000.0
    vol_target_annual_pct: float = 20.0  # scale pair notional to target spread vol


@dataclass
class PlatformConfig:
    costs: CostConfig = field(default_factory=CostConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
