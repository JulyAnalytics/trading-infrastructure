# systems/sarah/greeks_tool.py
"""
Greeks Decomposition Tool — Stage 2.
Uses analytic BS from systems/utils/pricing.py — no finite differences.
All outputs are directional-label-free.

Usage:
    from systems.sarah.greeks_tool import GreeksTool
    tool = GreeksTool()
    result = tool.analyze_position(
        ticker='SPY', flag='c', strike=580, expiration='2025-06-20',
        quantity=1, long_short='long'
    )
    print(result['interpretation'])
"""
from __future__ import annotations
import datetime
import json
from typing import Optional
import yfinance as yf
from loguru import logger

from config import VOL_DB_PATH, FRED_RISK_FREE_SERIES
from systems.utils.db import get_connection
from systems.utils.pricing import bs_greeks_full, bs_mispricing_flag, forward_price


class GreeksTool:
    """
    Analytic greek engine for single positions and portfolios.
    All greeks via analytic BS (no finite differences).
    No directional labels in any output.
    """

    VANNA_FLAG_THRESHOLD = 0.05
    CHARM_FLAG_THRESHOLD = 0.02
    VOMMA_FLAG_THRESHOLD = 50.0

    IV_FALLBACK = 18.0   # last-resort only; always logged as warning

    def analyze_position(
        self,
        ticker: str,
        flag: str,
        strike: float,
        expiration: str,
        quantity: int,
        long_short: str,
        rate: Optional[float] = None,
    ) -> dict:
        """
        Compute full greek profile for a single position.
        Returns position, market, greeks, greeks_scaled, bs_flag, interpretation.
        """
        tk = yf.Ticker(ticker)
        spot = tk.fast_info.get('lastPrice') or tk.fast_info.get('previousClose')
        div_yield = tk.fast_info.get('dividendYield') or 0.0

        if spot is None:
            raise ValueError(f"Cannot determine spot price for {ticker}")

        exp_date = datetime.datetime.strptime(expiration, '%Y-%m-%d').date()
        dte = (exp_date - datetime.date.today()).days
        if dte <= 0:
            raise ValueError(f"Expiration {expiration} is in the past or today")

        if rate is None:
            rate = self._get_rate()

        F = forward_price(spot, rate, div_yield, dte)
        t = dte / 365.0

        iv, iv_source = self._get_iv(ticker, strike, flag, spot, rate, dte, expiration)
        greeks = bs_greeks_full(flag, spot, strike, t, rate, div_yield, iv / 100.0)

        sign = 1 if long_short == 'long' else -1
        greeks_scaled = {k: v * sign * quantity * 100 for k, v in greeks.items()}

        skew_25d_rr = self._get_skew(ticker) or 0.0
        misprice = bs_mispricing_flag(greeks['delta'], skew_25d_rr)

        interpretation = self._format_interpretation(
            ticker, strike, flag, expiration, dte, long_short, quantity,
            spot, F, greeks, greeks_scaled, iv, iv_source, misprice
        )

        return {
            'position': {'ticker': ticker, 'flag': flag, 'strike': strike,
                         'expiration': expiration, 'quantity': quantity, 'long_short': long_short},
            'market':   {'spot': spot, 'forward': F, 'rate': rate,
                         'div_yield': div_yield, 'dte': dte, 'iv': iv, 'iv_source': iv_source},
            'greeks':        greeks,
            'greeks_scaled': greeks_scaled,
            'bs_flag':       misprice,
            'interpretation': interpretation,
        }

    def aggregate_portfolio(self, positions: list[dict]) -> dict:
        """Aggregate greeks across multiple analyzed positions."""
        net = {g: 0.0 for g in ['delta', 'gamma', 'theta_daily', 'vega', 'vanna', 'charm', 'vomma']}
        for pos in positions:
            for g in net:
                net[g] += pos['greeks_scaled'].get(g, 0.0)

        flags = []
        if abs(net['vanna']) > self.VANNA_FLAG_THRESHOLD:
            flags.append(
                f"VANNA CONCENTRATION: {net['vanna']:.3f} delta/vol-pt "
                f"(threshold \u00b1{self.VANNA_FLAG_THRESHOLD})"
            )
        if abs(net['charm']) > self.CHARM_FLAG_THRESHOLD:
            flags.append(
                f"CHARM CONCENTRATION: {net['charm']:.4f} daily delta drift "
                f"(threshold \u00b1{self.CHARM_FLAG_THRESHOLD})"
            )
        if abs(net['vomma']) > self.VOMMA_FLAG_THRESHOLD:
            flags.append(
                f"VOMMA CONCENTRATION: ${net['vomma']:.2f}/vol-pt "
                f"(threshold \u00b1${self.VOMMA_FLAG_THRESHOLD})"
            )

        return {'net_greeks': net, 'concentration_flags': flags}

    def _format_interpretation(
        self, ticker, strike, flag, expiration, dte, long_short, quantity,
        spot, forward, greeks, greeks_scaled, iv, iv_source, misprice
    ) -> str:
        opt_type = 'Call' if flag == 'c' else 'Put'
        d, ds = greeks, greeks_scaled
        lines = [
            f"GREEK INTERPRETATION — {ticker} {strike}{opt_type} exp {expiration}",
            "\u2500" * 66,
            f"Position:    {'LONG' if long_short == 'long' else 'SHORT'} {quantity} contract(s) | "
            f"Spot: ${spot:.2f} | Forward ({dte}d): ${forward:.2f} | "
            f"IV: {iv:.1f}% [{iv_source}]",
        ]
        if iv_source == 'fallback_18pct':
            lines.append(
                "\u26a0 IV SOURCE: fallback to 18.0% — chain lookup and stored history both failed. "
                "Greek magnitudes may be materially wrong. Recalculate with a valid IV."
            )
        lines += [
            "",
            f"Delta:       {d['delta']:+.3f} — equivalent exposure to "
            f"{abs(d['delta']) * quantity * 100:.0f} shares.",
            "",
            f"Gamma:       {d['gamma']:+.4f} — delta accelerates with spot moves.",
            f"             \u00b1$5 spot move shifts delta by ~{abs(d['gamma']) * 5:.3f}.",
            "",
            f"Theta:       ${ds['theta_daily']:+.2f}/day (at {dte} DTE).",
            f"             Theta accelerates nonlinearly as expiration approaches.",
            "",
            f"Vega:        ${ds['vega']:+.2f} per vol point.",
            "",
            f"Vanna:       {d['vanna']:+.4f} — delta shifts {d['vanna'] * (-3):.3f} "
            f"if IV drops 3 vol points.",
            f"             In a vol compression move, directional sensitivity changes "
            f"even if spot moves as expected.",
            "",
            f"Charm:       {d['charm']:+.5f}/day — delta drifts by "
            f"{d['charm'] * 10:.4f} in 10 calendar days with no market move.",
            "",
            f"Vomma:       {d['vomma']:+.4f}/vol-pt — vega convexity.",
            "",
        ]
        if misprice['bs_mispricing_flagged']:
            lines.append(f"\u26a0 BS ACCURACY: {misprice['warning']}")
        else:
            lines.append(
                f"BS accuracy: within reliability threshold "
                f"(\u0394={d['delta']:.2f} > {misprice['reliability_threshold']:.2f} "
                f"for {misprice['skew_regime']} skew)."
            )
        lines.append("\u2500" * 66)
        return "\n".join(lines)

    def _get_rate(self) -> float:
        try:
            import os, requests
            key = os.environ.get('FRED_API_KEY')
            if not key:
                return 0.045
            url = (
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={FRED_RISK_FREE_SERIES}&api_key={key}"
                f"&file_type=json&sort_order=desc&limit=1"
            )
            obs = requests.get(url, timeout=5).json()['observations']
            return float(obs[0]['value']) / 100.0
        except Exception:
            return 0.045

    def _get_iv(
        self, ticker: str, strike: float, flag: str,
        spot: float, rate: float, dte: int, expiration: str
    ) -> tuple[float, str]:
        """
        Returns (iv_vol_points, source_label).
        Sources in priority order: live chain → stored vol_signals → fallback 18%.
        Fallback ALWAYS logs a warning — never silent.
        """
        # 1. Live chain
        try:
            tk = yf.Ticker(ticker)
            chain_data = tk.option_chain(expiration)
            df = chain_data.calls if flag == 'c' else chain_data.puts
            df = df[df['bid'] > 0]
            if not df.empty:
                row = df.iloc[(df['strike'] - strike).abs().argsort()].iloc[0]
                mid = (row['bid'] + row['ask']) / 2.0
                from py_vollib.black_scholes.implied_volatility import implied_volatility as _pv
                iv = _pv(mid, spot, row['strike'], dte / 365.0, rate, flag)
                return float(iv * 100.0), 'live_chain'
        except Exception as e:
            logger.debug("{}: live IV lookup failed — {}", ticker, e)

        # 2. Stored ATM IV from trading.db
        try:
            conn = get_connection(VOL_DB_PATH)
            row = conn.execute(
                "SELECT atm_iv_30d FROM vol_signals WHERE ticker = ? "
                "ORDER BY date DESC LIMIT 1",
                [ticker]
            ).fetchone()
            conn.close()
            if row and row[0] is not None:
                logger.debug("{}: using stored ATM IV {:.1f}%", ticker, row[0])
                return float(row[0]), 'stored_atm_iv'
        except Exception as e:
            logger.debug("{}: stored IV lookup failed — {}", ticker, e)

        # 3. Last-resort fallback — always warn explicitly
        logger.warning(
            "{}: IV fallback to {:.1f}% — live chain and stored history both unavailable. "
            "Greek magnitudes will be approximate.",
            ticker, self.IV_FALLBACK
        )
        return self.IV_FALLBACK, 'fallback_18pct'

    def _get_skew(self, ticker: str) -> Optional[float]:
        try:
            conn = get_connection(VOL_DB_PATH)
            row = conn.execute(
                "SELECT skew_25d_rr FROM vol_signals WHERE ticker = ? "
                "ORDER BY date DESC LIMIT 1",
                [ticker]
            ).fetchone()
            conn.close()
            return float(row[0]) if row and row[0] is not None else None
        except Exception:
            return None


if __name__ == '__main__':
    tool = GreeksTool()
    result = tool.analyze_position(
        ticker='SPY', flag='c', strike=580,
        expiration=(datetime.date.today() + datetime.timedelta(days=45)).strftime('%Y-%m-%d'),
        quantity=1, long_short='long'
    )
    print(result['interpretation'])
    print("\nIV source:", result['market']['iv_source'])
