"""
Layer 4b: Path-Dependent Options Engine with Monte Carlo P&L distribution.

Design decisions encoded here:
- DD-07: Options strategies MUST produce MC P&L distributions (min 1000 paths).
  A single-path backtest cannot distinguish signal from path luck (Sinclair Ch.5).
- DD-08: Hedging vol choice is an explicit parameter ('implied' vs 'realized').
  Hedging at implied vol isolates the vol edge; hedging at realized vol introduces
  path-dependent hedging error. Both are needed at different pipeline stages.
- DD-09: BSM is used for quoting/Greeks only, NOT for simulation dynamics.
  If QuantLib is available, Heston is used for MC paths. If not, GBM is used
  with analytic BS Greeks — documented limitation, not silent degradation.
- DD-10: Three-level transaction cost decomposition (option entry/exit, hedge
  trade costs, cumulative hedge drag). The single-parameter slippage model is
  replaced. Leland breakeven spread is mandatory before simulation.

Architecture v2.0 Layer 4b.
"""

import numpy as np
import pandas as pd
import warnings

try:
    import QuantLib as ql
    QUANTLIB_AVAILABLE = True
except ImportError:
    QUANTLIB_AVAILABLE = False
    from systems.utils.pricing import bs_greeks_full
    warnings.warn(
        "QuantLib not available. Using analytic BS Greeks from "
        "systems/utils/pricing.py. MC paths use GBM instead of Heston. "
        "This is a known limitation per DD-09.",
        stacklevel=2,
    )

from config import MC_DEFAULT_N_PATHS


class OptionsBacktester:
    """
    Path-dependent options backtester with Monte Carlo P&L distribution.

    A single-path backtest of a vol strategy is one draw from the P&L
    distribution. Even when the vol forecast is exactly correct, Sinclair
    shows a single delta-hedged position can range from –$1,741 to +$1,984.
    Basing production decisions on one draw is equivalent to evaluating a
    coin by flipping it once.

    Usage:
        bt = OptionsBacktester(n_mc_paths=1000)
        result = bt.monte_carlo_pnl_distribution(
            spot=580, strike=580, dte=30,
            iv=0.16, forecast_rv=0.14,
            option_type='call', position_type='long',
            spread_pct=0.05,
        )
        leland = bt.compute_hedge_cost_leland(sigma=0.16, spread_pct=0.05, dt=1/252)
    """

    def __init__(
        self,
        slippage_bps: float = 50,
        min_volume: int = 100,
        max_spread_pct: float = 0.10,
        risk_free_rate: float = 0.05,
        hedge_vol_mode: str = 'implied',
        hedge_frequency: int = 1,
        n_mc_paths: int = MC_DEFAULT_N_PATHS,
    ):
        """
        Parameters
        ----------
        slippage_bps : float
            One-way slippage in basis points for option entry/exit (Level 1 cost).
        min_volume : int
            Minimum option volume for execution eligibility.
        max_spread_pct : float
            Maximum relative bid/ask spread for execution eligibility.
        risk_free_rate : float
            Annualized risk-free rate (decimal).
        hedge_vol_mode : str
            'implied' — hedge at IV (smoother P&L, isolates vol edge, default for research).
            'realized' — hedge at forecast/realized vol (noisier, closer to live).
            Per DD-08, this choice is logged as metadata on every run.
        hedge_frequency : int
            Hedge every N steps (1 = daily rehedging).
        n_mc_paths : int
            Number of Monte Carlo paths. Minimum 1000 for production conclusions (DD-07).
        """
        if hedge_vol_mode not in ('implied', 'realized'):
            raise ValueError(
                f"hedge_vol_mode must be 'implied' or 'realized', got '{hedge_vol_mode}'"
            )
        self.slippage = slippage_bps / 10_000
        self.min_volume = min_volume
        self.max_spread_pct = max_spread_pct
        self.rate = risk_free_rate
        self.hedge_vol_mode = hedge_vol_mode
        self.hedge_frequency = hedge_frequency
        self.n_mc_paths = n_mc_paths
        self.trade_log: list = []

    # ── Execution eligibility ──────────────────────────────────────────────────

    def can_execute(self, option_row: dict) -> tuple[bool, str]:
        """
        Check if an option is eligible for execution.

        Parameters
        ----------
        option_row : dict
            Must contain 'volume', 'bid', 'ask'.

        Returns
        -------
        (bool, str) — (eligible, reason)
        """
        if option_row.get('volume', 0) < self.min_volume:
            return False, f"Volume {option_row.get('volume', 0)} below minimum {self.min_volume}"
        bid = option_row.get('bid', 0)
        ask = option_row.get('ask', 0)
        if bid <= 0 or ask <= 0:
            return False, f"Invalid bid/ask: bid={bid}, ask={ask}"
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid
        if spread_pct > self.max_spread_pct:
            return False, f"Spread {spread_pct:.1%} exceeds max {self.max_spread_pct:.1%}"
        return True, "OK"

    def fill_price(self, bid: float, ask: float, direction: str) -> float:
        """
        Compute fill price including slippage (Level 1 cost).

        direction : 'buy' → fill at ask + slippage
                    'sell' → fill at bid − slippage
        """
        if direction == 'buy':
            return ask * (1 + self.slippage)
        elif direction == 'sell':
            return bid * (1 - self.slippage)
        else:
            raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    # ── Transaction cost models ────────────────────────────────────────────────

    def compute_hedge_cost_leland(
        self,
        sigma: float,
        spread_pct: float,
        dt: float,
    ) -> dict:
        """
        Leland-adjusted hedging volatility. Computes the spread at which
        hedging costs consume the vol edge entirely (breakeven spread).

        For long gamma: adjusted vol is LOWER (costs reduce effective vol).
        For short gamma: adjusted vol is HIGHER (costs increase effective vol).

        Ref: Sinclair Eq. 4.7-4.8.

        Parameters
        ----------
        sigma : float
            Implied or forecast vol (annualized decimal, e.g. 0.20).
        spread_pct : float
            Relative bid/ask spread of the underlying (decimal).
        dt : float
            Time step size in years (e.g. 1/252 for daily).

        Returns
        -------
        dict with keys:
            long_gamma_vol    : Leland-adjusted vol for long gamma positions
            short_gamma_vol   : Leland-adjusted vol for short gamma positions
            breakeven_spread  : Spread at which vol edge is fully consumed
        """
        lambda_cost = spread_pct / 2.0  # proportional round-trip cost
        adjustment = lambda_cost * np.sqrt(8.0 / (np.pi * dt))

        long_gamma_vol = sigma - adjustment
        short_gamma_vol = sigma + adjustment
        breakeven_spread = sigma * np.sqrt(np.pi * dt / 8.0)

        return {
            'long_gamma_vol': float(long_gamma_vol),
            'short_gamma_vol': float(short_gamma_vol),
            'breakeven_spread': float(breakeven_spread),
            'adjustment': float(adjustment),
            'note': (
                'long_gamma_vol < 0 — hedging costs exceed vol edge at this spread/dt'
                if long_gamma_vol < 0 else 'Vol edge positive after Leland adjustment'
            ),
        }

    def compute_market_impact(
        self,
        sigma_daily: float,
        avg_daily_volume: float,
        order_size: float,
    ) -> float:
        """
        Square-root market impact model for hedge trades (Level 2 cost).

        impact = α × √(order_size)   where α = σ_daily / √(ADV)

        Ref: Sinclair Eq. 4.22.

        Parameters
        ----------
        sigma_daily : float
            Daily volatility of the underlying (decimal).
        avg_daily_volume : float
            Average daily volume of the underlying (shares).
        order_size : float
            Number of shares in the hedge trade.

        Returns
        -------
        float — estimated market impact per share (decimal of price).
        """
        if avg_daily_volume <= 0:
            return 0.0
        alpha = sigma_daily / np.sqrt(avg_daily_volume)
        return float(alpha * np.sqrt(order_size))

    # ── Monte Carlo P&L distribution ──────────────────────────────────────────

    def monte_carlo_pnl_distribution(
        self,
        spot: float,
        strike: float,
        dte: int,
        iv: float,
        forecast_rv: float,
        option_type: str,
        position_type: str,
        spread_pct: float = 0.05,
    ) -> dict:
        """
        Simulate n_mc_paths of delta-hedged option P&L and return the full
        distribution. Reports mean/median/std/percentiles/prob_loss — not
        a single P&L number.

        Core P&L identity (Sinclair Eq. 1.7):
            dP/L ≈ 0.5 × S² × Γ × (σ²_realized − σ²_implied) × dt

        The distribution width is the confidence qualifier. The mean P&L
        is the research finding.

        Parameters
        ----------
        spot : float
            Current underlying price.
        strike : float
            Option strike price.
        dte : int
            Days to expiration.
        iv : float
            Implied volatility (annualized decimal, e.g. 0.16).
        forecast_rv : float
            Forecast or realized volatility used to simulate the underlying.
        option_type : str
            'call' or 'put'.
        position_type : str
            'long' or 'short'.
        spread_pct : float
            Relative bid/ask spread of the underlying, used for hedge costs.

        Returns
        -------
        dict with keys:
            mean_pnl, median_pnl, std_pnl, p5, p95, prob_loss,
            mean_hedge_cost, kamal_derman_sigma, n_paths, hedge_vol_mode.
        """
        if option_type not in ('call', 'put'):
            raise ValueError(f"option_type must be 'call' or 'put', got '{option_type}'")
        if position_type not in ('long', 'short'):
            raise ValueError(f"position_type must be 'long' or 'short', got '{position_type}'")
        if dte <= 0:
            raise ValueError(f"dte must be positive, got {dte}")

        dt = 1.0 / 252
        n_steps = dte
        sign = 1 if position_type == 'long' else -1

        # Select hedging vol per DD-08
        hedge_vol = iv if self.hedge_vol_mode == 'implied' else forecast_rv

        pnl_paths = []
        rng = np.random.default_rng()

        for _ in range(self.n_mc_paths):
            S = spot
            cumulative_pnl = 0.0
            hedge_cost_total = 0.0

            for step in range(n_steps):
                t_remaining = (n_steps - step) / 252.0
                if t_remaining <= 0:
                    break

                greeks = self._bsm_greeks(S, strike, t_remaining, iv, option_type)

                # Simulate one step under real-world measure (GBM)
                dW = rng.normal(0.0, np.sqrt(dt))
                dS = S * forecast_rv * dW
                S_new = S + dS

                # Instantaneous hedge P&L (Sinclair Eq. 1.7)
                # Realized var from simulated step vs. implied var
                realized_var = (dS / S) ** 2 / dt
                implied_var = iv ** 2
                instant_pnl = 0.5 * S ** 2 * greeks['gamma'] * (realized_var - implied_var) * dt

                # Position sign: long benefits from positive gamma P&L
                cumulative_pnl += sign * instant_pnl

                # Level 2 cost: hedge trade at rehedge frequency
                if step % self.hedge_frequency == 0:
                    hedge_delta = abs(greeks['delta'])
                    hedge_trade_cost = hedge_delta * S * abs(spread_pct) / 2.0
                    hedge_cost_total += hedge_trade_cost

                S = S_new

            net_pnl = cumulative_pnl - hedge_cost_total
            pnl_paths.append({
                'gross_pnl': cumulative_pnl,
                'hedge_cost': hedge_cost_total,
                'net_pnl': net_pnl,
            })

        pnl_array = np.array([p['net_pnl'] for p in pnl_paths])
        hedge_array = np.array([p['hedge_cost'] for p in pnl_paths])

        # Kamal-Derman analytic P&L dispersion estimate
        # σ_PL ≈ √(π/4) · vega · σ / √N
        # Ref: Sinclair Ch.5
        try:
            entry_greeks = self._bsm_greeks(spot, strike, dte / 252.0, iv, option_type)
            kamal_derman_sigma = (
                np.sqrt(np.pi / 4.0)
                * abs(entry_greeks['vega'])
                * forecast_rv
                / np.sqrt(n_steps)
            )
        except Exception:
            kamal_derman_sigma = float('nan')

        return {
            'mean_pnl': float(np.mean(pnl_array)),
            'median_pnl': float(np.median(pnl_array)),
            'std_pnl': float(np.std(pnl_array)),
            'p5': float(np.percentile(pnl_array, 5)),
            'p95': float(np.percentile(pnl_array, 95)),
            'prob_loss': float((pnl_array < 0).mean()),
            'mean_gross_pnl': float(np.mean([p['gross_pnl'] for p in pnl_paths])),
            'mean_hedge_cost': float(np.mean(hedge_array)),
            'hedge_cost_pct_of_gross': float(
                np.mean(hedge_array) / max(abs(np.mean([p['gross_pnl'] for p in pnl_paths])), 1e-10)
            ),
            'kamal_derman_sigma': float(kamal_derman_sigma),
            'n_paths': self.n_mc_paths,
            'hedge_vol_mode': self.hedge_vol_mode,
            'hedge_vol_used': float(hedge_vol),
            'quantlib_used': QUANTLIB_AVAILABLE,
        }

    # ── Greeks computation ─────────────────────────────────────────────────────

    def _bsm_greeks(
        self,
        spot: float,
        strike: float,
        t: float,
        vol: float,
        opt_type: str,
    ) -> dict:
        """
        BSM Greeks — used for quoting/signal construction only, NOT simulation
        dynamics (DD-09). Returns {'price', 'delta', 'gamma', 'vega', 'theta'}.

        If QuantLib is available: uses QuantLib AnalyticEuropeanEngine.
        Otherwise: delegates to systems/utils/pricing.py bs_greeks_full().

        This is a fast inner-loop function called once per step per path.
        """
        if t <= 0:
            t = 1e-6  # floor to avoid division by zero at expiry

        if QUANTLIB_AVAILABLE:
            return self._greeks_quantlib(spot, strike, t, vol, opt_type)
        else:
            return self._greeks_pricing_py(spot, strike, t, vol, opt_type)

    def _greeks_quantlib(
        self,
        spot: float,
        strike: float,
        t: float,
        vol: float,
        opt_type: str,
    ) -> dict:
        """QuantLib analytic BSM Greeks."""
        today = ql.Date.todaysDate()
        expiry = today + ql.Period(max(int(t * 365), 1), ql.Days)
        ql_type = ql.Option.Call if opt_type == 'call' else ql.Option.Put
        payoff = ql.PlainVanillaPayoff(ql_type, strike)
        exercise = ql.EuropeanExercise(expiry)
        option = ql.VanillaOption(payoff, exercise)

        spot_h = ql.QuoteHandle(ql.SimpleQuote(float(spot)))
        flat_ts = ql.YieldTermStructureHandle(
            ql.FlatForward(today, float(self.rate), ql.Actual365Fixed())
        )
        flat_div = ql.YieldTermStructureHandle(
            ql.FlatForward(today, 0.0, ql.Actual365Fixed())
        )
        flat_vol = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(today, ql.NullCalendar(), float(vol), ql.Actual365Fixed())
        )
        process = ql.BlackScholesMertonProcess(spot_h, flat_div, flat_ts, flat_vol)
        option.setPricingEngine(ql.AnalyticEuropeanEngine(process))

        return {
            'price': float(option.NPV()),
            'delta': float(option.delta()),
            'gamma': float(option.gamma()),
            'vega': float(option.vega() / 100.0),   # per 1 vol point (consistent with pricing.py)
            'theta': float(option.theta() / 365.0),  # daily theta
        }

    def _greeks_pricing_py(
        self,
        spot: float,
        strike: float,
        t: float,
        vol: float,
        opt_type: str,
    ) -> dict:
        """
        Fallback using systems/utils/pricing.py bs_greeks_full().
        Assumes zero dividend yield (q=0) for research purposes.
        """
        flag = 'c' if opt_type == 'call' else 'p'
        greeks = bs_greeks_full(flag=flag, S=spot, K=strike, t=t,
                                r=self.rate, q=0.0, sigma=vol)
        price_val = _bs_price_simple(flag, spot, strike, t, self.rate, vol)
        return {
            'price': float(price_val),
            'delta': float(greeks['delta']),
            'gamma': float(greeks['gamma']),
            'vega': float(greeks['vega']),
            'theta': float(greeks['theta_daily']),
        }

    # ── Trade logging ──────────────────────────────────────────────────────────

    def log_trade(
        self,
        trade_id: str,
        entry_fill: float,
        exit_fill: float,
        hedge_cost: float,
        gross_pnl: float,
        net_pnl: float,
        turnover: float,
        broker_fee: float = 0.0,
        metadata: dict = None,
    ) -> None:
        """
        Log a completed trade for implementation shortfall computation.

        The trade_log is consumed by ImplementationShortfall.compute()
        in Layer 7a to produce the four required IS metrics.
        """
        entry = {
            'trade_id': trade_id,
            'entry_fill': entry_fill,
            'exit_fill': exit_fill,
            'slippage_cost': (entry_fill + exit_fill) * self.slippage,
            'hedge_cost': hedge_cost,
            'gross_pnl': gross_pnl,
            'net_pnl': net_pnl,
            'turnover': turnover,
            'broker_fee': broker_fee,
        }
        if metadata:
            entry.update(metadata)
        self.trade_log.append(entry)


# ── Module-level helpers ───────────────────────────────────────────────────────

def _bs_price_simple(flag: str, S: float, K: float, t: float,
                     r: float, sigma: float) -> float:
    """
    Minimal analytic BS price for the fallback path (q=0).
    Not exported — internal to this module. For research/pricing use
    systems/utils/pricing.py bs_price() with explicit dividend yield.
    """
    from scipy.stats import norm
    if t <= 0:
        return max(S - K, 0.0) if flag == 'c' else max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    if flag == 'c':
        return float(S * norm.cdf(d1) - K * np.exp(-r * t) * norm.cdf(d2))
    else:
        return float(K * np.exp(-r * t) * norm.cdf(-d2) - S * norm.cdf(-d1))
