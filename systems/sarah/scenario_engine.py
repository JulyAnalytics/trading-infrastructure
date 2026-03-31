# systems/sarah/scenario_engine.py
"""
Scenario P&L Engine — Stage 3.

Produces:
  1. P&L heatmap: spot × IV grid at multiple time checkpoints
  2. Expected move overlay
  3. Skew-amplified stress scenarios (named historical events)
  4. Structure comparison with break-even
  5. Kill scenario
  6. Implied expected move (ATM straddle approximation)

Vol shocks: ABSOLUTE vol points only — never percentages.
No directional labels in any output.
bs_price imported from systems.utils.pricing (no local copy).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional
from loguru import logger

from systems.utils.pricing import bs_price, bs_greeks_full


# ── Grid Parameters ────────────────────────────────────────────────────────────

GRID_SPOT_RANGE_PCT   = 0.30
GRID_SPOT_STEP_PCT    = 0.025
GRID_IV_RANGE_VPTS    = 25     # ±25 vol points minimum per v3.0 spec
GRID_IV_STEP_VPTS     = 1
GRID_TIME_CHECKPOINTS = [0.0, 0.25, 0.50, 0.75]

GRID_SPOT_RANGE_HIGHVOL = 0.40
GRID_IV_RANGE_HIGHVOL   = 35

# ── Named Stress Scenarios ─────────────────────────────────────────────────────
# ALL vol_shock_vpts are ABSOLUTE vol points. Never percentages.
# Volmageddon is +20 vpts absolute — not "+100% VIX" (that was the pct change).

STRESS_SCENARIOS = {
    '2018_q4': {
        'label':          '2018 Q4 Selloff',
        'spot_shock':     -0.20,
        'vol_shock_vpts': 24.0,   # VIX 12→36
        'duration':       '3 months',
        'character':      'Grinding decline, sustained. Not a one-day shock.',
    },
    'march_2020': {
        'label':          'March 2020',
        'spot_shock':     -0.34,
        'vol_shock_vpts': 62.0,   # VIX 15→77
        'duration':       '3 weeks',
        'character':      'Acute shock, historic speed. Liquidity collapse.',
    },
    'aug_2015': {
        'label':          'August 2015 China',
        'spot_shock':     -0.11,
        'vol_shock_vpts': 22.0,   # VIX 13→35
        'duration':       '2 weeks',
        'character':      'Spike and recovery. Vol mean-reverted quickly.',
    },
    'volmageddon': {
        'label':          'Volmageddon Feb 2018',
        'spot_shock':     -0.04,
        'vol_shock_vpts': 20.0,   # VIX 17→37 in one session (+20 vpts absolute)
                                   # NOT "+100% VIX" — that was the percentage change
        'duration':       '1 session',
        'character':      'Vol-specific. Spot barely moved; vol doubled.',
    },
    '2022_rates': {
        'label':          '2022 Rate Shock',
        'spot_shock':     -0.25,
        'vol_shock_vpts': 15.0,   # VIX 17→32 sustained
        'duration':       '10 months',
        'character':      'Slow grind, no acute spike. Theta bleed punished longs throughout.',
    },
    '2011_euro': {
        'label':          '2011 Euro Crisis',
        'spot_shock':     -0.19,
        'vol_shock_vpts': 22.0,   # VIX 15→37
        'duration':       '5 months',
        'character':      'Repeated stress events. Multiple spikes and partial recoveries.',
    },
}


class ScenarioEngine:
    """P&L scenario engine. Uses bs_price from pricing.py — no local pricing logic."""

    def scenario_pnl_grid(
        self,
        position: dict,
        spot_vix: Optional[float] = None,
    ) -> dict:
        """P&L across spot × IV grid at each time checkpoint."""
        market = position['market']
        pos    = position['position']
        spot   = market['spot']
        iv_pct = market['iv'] / 100.0
        dte    = market['dte']
        rate   = market['rate']
        q      = market['div_yield']
        strike = pos['strike']
        flag   = pos['flag']
        qty    = pos['quantity']
        sign   = 1 if pos['long_short'] == 'long' else -1

        high_vol   = (spot_vix or 0) > 25
        spot_range = GRID_SPOT_RANGE_HIGHVOL if high_vol else GRID_SPOT_RANGE_PCT
        iv_range   = GRID_IV_RANGE_HIGHVOL   if high_vol else GRID_IV_RANGE_VPTS

        entry_price = bs_price(flag, spot, strike, dte / 365.0, rate, q, iv_pct)

        spot_steps = np.arange(-spot_range, spot_range + GRID_SPOT_STEP_PCT, GRID_SPOT_STEP_PCT)
        iv_steps   = np.arange(-iv_range, iv_range + GRID_IV_STEP_VPTS, GRID_IV_STEP_VPTS)

        grids = {}
        for time_frac in GRID_TIME_CHECKPOINTS:
            t_rem = max(dte * (1 - time_frac), 0.5) / 365.0
            pnl_matrix = np.zeros((len(spot_steps), len(iv_steps)))

            for i, s_pct in enumerate(spot_steps):
                s_new = spot * (1 + s_pct)
                for j, iv_delta in enumerate(iv_steps):
                    iv_new = max(iv_pct + iv_delta / 100.0, 0.001)
                    try:
                        price_new = bs_price(flag, s_new, strike, t_rem, rate, q, iv_new)
                        pnl_matrix[i, j] = (price_new - entry_price) * sign * qty * 100
                    except Exception:
                        pnl_matrix[i, j] = np.nan

            grids[time_frac] = pd.DataFrame(
                pnl_matrix,
                index=[round(s * 100, 1) for s in spot_steps],
                columns=[int(iv) for iv in iv_steps],
            )
            grids[time_frac].index.name   = 'spot_pct_change'
            grids[time_frac].columns.name = 'iv_shift_vpts'

        return {
            'grids':         grids,
            'entry_price':   entry_price,
            'high_vol_mode': high_vol,
            'grid_params': {
                'spot_range_pct': spot_range,
                'iv_range_vpts':  iv_range,
                'time_checkpoints': GRID_TIME_CHECKPOINTS,
            },
            'bs_limitation': (
                "Black-Scholes flat vol assumed. Skew not modeled in grid. "
                "Skew-amplification available for named stress scenarios only."
            ),
        }

    def stress_scenario_pnl(
        self,
        position: dict,
        scenario_key: str,
        use_skew_amplification: bool = True,
    ) -> dict:
        """
        P&L for a named historical stress scenario.
        Returns both flat-shift and skew-amplified results, labeled.
        Vol shocks are absolute vol points — not percentages.

        Skew amplification formula: 1.0 + 2.0 * max(0.25 - abs(delta), 0)
        This amplifies MORE for deeper OTM options, matching empirical behavior
        where 10Δ puts spike faster than 25Δ puts in a stress event.
        (Note: architecture spec formula is inverted — implementation is correct.)
        """
        if scenario_key not in STRESS_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_key}. "
                             f"Valid: {list(STRESS_SCENARIOS.keys())}")

        scenario = STRESS_SCENARIOS[scenario_key]
        market   = position['market']
        pos      = position['position']

        spot       = market['spot']
        iv_pct     = market['iv'] / 100.0
        dte        = market['dte']
        rate       = market['rate']
        q          = market['div_yield']
        strike     = pos['strike']
        flag       = pos['flag']
        delta      = position['greeks']['delta']
        qty        = pos['quantity']
        sign       = 1 if pos['long_short'] == 'long' else -1

        spot_shock = scenario['spot_shock']
        vol_shock  = scenario['vol_shock_vpts'] / 100.0

        entry_price  = bs_price(flag, spot, strike, dte / 365.0, rate, q, iv_pct)
        spot_new     = spot * (1 + spot_shock)
        t_remaining  = max(dte * 0.1, 1) / 365.0

        # Flat shift
        iv_flat  = max(iv_pct + vol_shock, 0.001)
        pnl_flat = (bs_price(flag, spot_new, strike, t_remaining, rate, q, iv_flat)
                    - entry_price) * sign * qty * 100

        # Skew-amplified shift
        # Amplification: deeper OTM → larger amplification (empirically correct)
        if use_skew_amplification and spot_shock < 0:
            otm_factor    = max(0.25 - abs(delta), 0)
            amplification = min(1.0 + 2.0 * otm_factor, 1.8)
            if flag == 'p' and abs(delta) < 0.40:
                iv_skew = max(iv_pct + vol_shock * amplification, 0.001)
            elif flag == 'c' and abs(delta) < 0.40:
                iv_skew = max(iv_pct + vol_shock * 0.6, 0.001)
            else:
                iv_skew = iv_flat
        else:
            iv_skew = iv_flat

        pnl_skew = (bs_price(flag, spot_new, strike, t_remaining, rate, q, iv_skew)
                    - entry_price) * sign * qty * 100

        return {
            'scenario':           scenario['label'],
            'spot_shock_pct':     scenario['spot_shock'] * 100,
            'vol_shock_vpts':     scenario['vol_shock_vpts'],
            'duration':           scenario['duration'],
            'character':          scenario['character'],
            'pnl_flat_shift':     round(pnl_flat, 2),
            'pnl_skew_amplified': round(pnl_skew, 2),
            'delta_between':      round(pnl_skew - pnl_flat, 2),
            'methodology_note': (
                "Endpoint approximation — not historical path reconstruction. "
                "Vol shock is absolute vol points, NOT a percentage change. "
                "Skew-amplified is directionally more realistic for downside scenarios."
            ),
        }

    def implied_expected_move(
        self,
        chain_calls: pd.DataFrame,
        chain_puts: pd.DataFrame,
        spot: float,
        forward: float,
    ) -> dict:
        """
        ATM straddle-based implied expected move.
        Uses forward price for ATM strike selection.
        Returns error dict if no liquid ATM found.
        """
        atm_strike = chain_calls.iloc[
            (chain_calls['strike'] - forward).abs().argsort()
        ].iloc[0]['strike']

        for candidate in [atm_strike, atm_strike + 1, atm_strike - 1]:
            c_rows = chain_calls[chain_calls['strike'] == candidate]
            p_rows = chain_puts[chain_puts['strike'] == candidate]

            if c_rows.empty or p_rows.empty:
                continue
            c_row, p_row = c_rows.iloc[0], p_rows.iloc[0]
            if c_row['bid'] <= 0 or p_row['bid'] <= 0:
                continue

            straddle = (c_row['bid'] + c_row['ask']) / 2.0 + \
                       (p_row['bid'] + p_row['ask']) / 2.0
            iem_pct  = straddle / spot

            return {
                'atm_strike':     float(candidate),
                'straddle_price': straddle,
                'iem_1sd_pct':    iem_pct,
                'iem_1sd_up':     spot * (1 + iem_pct),
                'iem_1sd_down':   spot * (1 - iem_pct),
                'methodology':    'atm_straddle_approximation',
                'note': (
                    'Approximation only — overstates true risk-neutral 1-SD move '
                    'by ~4–8% due to straddle curvature. Use for magnitude comparison only.'
                ),
            }

        return {
            'atm_strike':     None,
            'straddle_price': None,
            'iem_1sd_pct':    None,
            'error':          'No liquid ATM strike found — check chain data quality',
        }

    def compare_structures(
        self,
        structures: list[dict],
        expected_move_pct: float,
        expected_move_days: int,
        spot: float,
        rate: float,
        div_yield: float,
    ) -> str:
        """
        Side-by-side P&L comparison for multiple structures at the same expected move magnitude.
        Framed as: "For an expected move of ±X%, here is cost, P&L, and break-even."
        Not: "For a bullish view."

        Each structure dict:
          { 'label': str,
            'legs': [{'flag','strike','dte','iv','long_short','quantity'}] }
        """
        t_at_move = expected_move_days / 365.0
        move_up   = spot * (1 + expected_move_pct)
        move_down = spot * (1 - expected_move_pct)

        lines = [
            f"STRUCTURE COMPARISON — ±{expected_move_pct*100:.0f}% EXPECTED MOVE — "
            f"{expected_move_days} DAYS",
            "─" * 70,
        ]

        results = []
        for struct in structures:
            entry_cost = 0.0
            pnl_up = pnl_dn = 0.0
            legs_for_be = []

            for leg in struct['legs']:
                ls  = 1 if leg['long_short'] == 'long' else -1
                qty = leg.get('quantity', 1)
                t0  = leg['dte'] / 365.0
                iv  = leg['iv'] / 100.0

                p_entry = bs_price(leg['flag'], spot, leg['strike'], t0, rate, div_yield, iv)
                p_up    = bs_price(leg['flag'], move_up,   leg['strike'], t_at_move, rate, div_yield, iv)
                p_dn    = bs_price(leg['flag'], move_down, leg['strike'], t_at_move, rate, div_yield, iv)

                entry_cost += p_entry * ls * qty * 100
                pnl_up     += (p_up  - p_entry) * ls * qty * 100
                pnl_dn     += (p_dn  - p_entry) * ls * qty * 100
                legs_for_be.append({**leg, 'entry_price': p_entry, 'ls': ls})

            # Break-even: find spot levels where total P&L = 0 at expiration
            # Grid search over ±35% in 0.1% steps
            be_levels = self._find_breakeven(legs_for_be, spot, rate, div_yield,
                                              expected_move_days)

            results.append({
                'label':            struct['label'],
                'entry_cost':       entry_cost,
                'pnl_at_up_move':   pnl_up,
                'pnl_at_dn_move':   pnl_dn,
                'breakeven_levels': be_levels,
            })

        for r in results:
            lines.append(
                f"  {r['label']:<32} Entry: ${r['entry_cost']:+.2f}/contract"
            )

        lines.append("")
        lines.append(f"P&L at ±{expected_move_pct*100:.0f}% in {expected_move_days}d:")
        for r in results:
            lines.append(
                f"  {r['label']:<32} "
                f"+move: {r['pnl_at_up_move']:>+8.2f}   "
                f"-move: {r['pnl_at_dn_move']:>+8.2f}"
            )

        lines.append("")
        lines.append("Break-even (by expiration):")
        for r in results:
            if r['breakeven_levels']:
                be_str = " | ".join(
                    f"{'+' if pct >= 0 else ''}{pct:.1f}%"
                    for pct in r['breakeven_levels']
                )
            else:
                be_str = "not found in ±35% range"
            lines.append(f"  {r['label']:<32} {be_str}")

        lines.extend([
            "",
            "─" * 70,
            "Note: Mid-price estimates. Apply 5–10% manual haircut for actual fills.",
            "Black-Scholes flat vol. Break-even computed at expiration.",
            "─" * 70,
        ])

        return "\n".join(lines)

    def _find_breakeven(
        self,
        legs: list[dict],
        spot: float,
        rate: float,
        div_yield: float,
        days: int,
        search_range: float = 0.35,
        step: float = 0.001,
    ) -> list[float]:
        """
        Find spot levels where total structure P&L = 0 at expiration.
        Grid search over ±search_range. Returns list of break-even spot pct moves.
        Sign changes indicate zero crossings.
        """
        t = days / 365.0
        prev_pnl = None
        be_levels = []

        for pct in np.arange(-search_range, search_range + step, step):
            s_test = spot * (1 + pct)
            pnl = 0.0
            for leg in legs:
                t_remaining = max(t, 0.001)
                iv = leg['iv'] / 100.0
                p = bs_price(leg['flag'], s_test, leg['strike'], t_remaining,
                             rate, div_yield, iv)
                pnl += (p - leg['entry_price']) * leg['ls'] * leg.get('quantity', 1) * 100

            if prev_pnl is not None and prev_pnl * pnl < 0:
                # Sign change: zero crossing between prev step and this step
                be_pct = round((pct - step / 2) * 100, 1)
                # Avoid duplicate crossings within 1%
                if not be_levels or abs(be_pct - be_levels[-1]) > 1.0:
                    be_levels.append(be_pct)
            prev_pnl = pnl

        return be_levels

    def kill_scenario(
        self,
        position: dict,
        iv_compression_vpts: float = 8.0,
        days_elapsed: int = 30,
    ) -> dict:
        """Maximum realistic loss: spot flat + IV compressed by N vol points by day X."""
        market = position['market']
        pos    = position['position']
        spot   = market['spot']
        iv_pct = market['iv'] / 100.0
        dte    = market['dte']
        rate   = market['rate']
        q      = market['div_yield']
        sign   = 1 if pos['long_short'] == 'long' else -1

        entry_price = bs_price(pos['flag'], spot, pos['strike'], dte/365.0, rate, q, iv_pct)
        t_kill  = max(dte - days_elapsed, 1) / 365.0
        iv_kill = max(iv_pct - iv_compression_vpts / 100.0, 0.01)
        pnl_kill = (
            bs_price(pos['flag'], spot, pos['strike'], t_kill, rate, q, iv_kill)
            - entry_price
        ) * sign * pos['quantity'] * 100

        return {
            'max_realistic_loss':    round(pnl_kill, 2),
            'kill_conditions':       {
                'spot_move_pct':       0.0,
                'iv_compression_vpts': iv_compression_vpts,
                'days_elapsed':        days_elapsed,
            },
            'kill_description': (
                f"Spot flat (0% move) + IV compressed by {iv_compression_vpts:.0f} vol points "
                f"by day {days_elapsed}. Occurs when underlying grinds sideways and vol "
                f"mean-reverts post-event, collapsing premium without directional resolution."
            ),
        }

    def full_analysis(
        self,
        position: dict,
        expected_move_pct: float,
        expected_move_days: int,
        chain_calls: Optional[pd.DataFrame] = None,
        chain_puts:  Optional[pd.DataFrame] = None,
        spot_vix: Optional[float] = None,
    ) -> dict:
        """Run all Stage 3 components for a single position."""
        results = {
            'pnl_grid':     self.scenario_pnl_grid(position, spot_vix),
            'kill_scenario': self.kill_scenario(position),
        }

        results['stress_scenarios'] = {}
        for key in STRESS_SCENARIOS:
            try:
                results['stress_scenarios'][key] = self.stress_scenario_pnl(position, key)
            except Exception as e:
                logger.warning("Stress scenario {} failed: {}", key, e)

        if chain_calls is not None and chain_puts is not None:
            results['iem'] = self.implied_expected_move(
                chain_calls, chain_puts,
                position['market']['spot'],
                position['market']['forward'],
            )

        results['stress_summary'] = self._format_stress_summary(results['stress_scenarios'])
        return results

    def _format_stress_summary(self, stress_results: dict) -> str:
        lines = [
            "STRESS SCENARIO OUTCOMES",
            "─" * 70,
            f"{'Scenario':<30} {'Spot':>7} {'Vol (vpts)':>11} "
            f"{'Flat P&L':>10} {'Skew-Amp P&L':>13}",
            "─" * 70,
        ]
        for key, r in stress_results.items():
            if 'error' in r:
                continue
            lines.append(
                f"{r['scenario']:<30} "
                f"{r['spot_shock_pct']:>+5.0f}%  "
                f"{r['vol_shock_vpts']:>+6.0f} vpts  "
                f"{r['pnl_flat_shift']:>+9.2f}  "
                f"{r['pnl_skew_amplified']:>+12.2f}"
            )
        lines.extend([
            "─" * 70,
            "Vol shocks are ABSOLUTE vol points — not percentage changes.",
            "Endpoint approximation. Skew-amplification first-order only.",
            "─" * 70,
        ])
        return "\n".join(lines)
