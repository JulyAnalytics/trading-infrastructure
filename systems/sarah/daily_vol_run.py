# systems/sarah/daily_vol_run.py
"""
Daily vol surface run — Stage 1 orchestrator.

Execution sequence:
  1. Read regime_state.json (prerequisite — fails loudly if missing or stale)
  2. Fetch risk-free rate from FRED (or fallback to cached)
  3. For each ticker (VOL_TICKERS, or an ad-hoc batch):
     a. Fetch options chain
     b. Build term structure
     c. Extract skew
     d. Compute signals
     e. Write to trading.db
  4. Write vol_signals.json to data/outputs/ — DAILY MODE ONLY

Two modes:
  run_daily_vol()                    → the configured daily universe
  run_daily_vol(tickers=["AAOI"])    → ad-hoc batch (RCS trade intake,
                                        earnings-week screening). Same
                                        pipeline, same DB writes; skips the
                                        vol_signals.json snapshot.

Run directly: python systems/sarah/daily_vol_run.py [TICKER ...]
Or call run_daily_vol() programmatically (from the job runner).
"""
from __future__ import annotations
import datetime
import json
import os
import time
from pathlib import Path
from loguru import logger

from config import (
    OUTPUTS_DIR, VOL_DB_PATH, VOL_TICKERS,
    FRED_RISK_FREE_SERIES, VOL_IVR_MIN_HISTORY_DAYS,
)
from systems.params import get_params
from systems.utils.db import get_connection
from systems.utils.pricing import forward_price
from systems.data_feeds.options_feed import fetch_options_chain
from systems.data_feeds.cboe_feed import fetch_vix_term_structure, fetch_vvix_daily
from research.signals.vol_surface import (
    build_term_structure, extract_skew_slice, extract_skew_by_delta,
    compute_pc_oi_ratios,
)
from research.signals.vol_signals import (
    term_structure_slopes, backward_vrp_proxy, iv_context
)
from systems.sarah.vol_db import (
    initialize_vol_schema, upsert_vol_signals, upsert_vol_surface,
)
from systems.sarah.catalyst_calendar import next_earnings_date


# Seed default for the max acceptable regime_state.json age. The LIVE limit is
# the GUI-editable registry value (SarahParams.regime_staleness_hours); this
# constant only documents the default. 80h covers the overnight weekday cycle
# (~14h) and the full weekend (Friday→Monday ~62h): Friday's regime is the
# correct most-recent signal for Monday, which is not staleness.
MAX_REGIME_STATE_AGE_HOURS = 80


def _load_regime_state(skip_staleness_check: bool = False) -> dict:
    """Load and validate regime_state.json. Fails loudly if missing or too stale.

    skip_staleness_check relaxes the AGE gate only — the file must still
    exist, because the regime label is stamped on every signals row. It is
    used for weekend screening runs (the regime has not moved, it is just
    old); a stale regime on a weekday remains a hard failure (CLAUDE.md
    rule 4).
    """
    p = Path(OUTPUTS_DIR) / 'regime_state.json'
    assert p.exists(), (
        f"MISSING: {p}\n"
        "Marcus pipeline must run and write regime_state.json first. "
        "See Task 000 for setup."
    )
    data = json.loads(p.read_text())
    written = datetime.datetime.fromisoformat(data['written_at'])
    age_h = (datetime.datetime.now() - written).total_seconds() / 3600
    limit_h = get_params("sarah").regime_staleness_hours
    if skip_staleness_check:
        if age_h >= limit_h:
            logger.warning(
                "regime_state.json is {:.1f}h old (limit {}h) — staleness gate "
                "SKIPPED for this screening run. Signals are stamped with the "
                "stale regime '{}'; do not treat them as execution-grade.",
                age_h, limit_h, data.get('regime_state'))
        return data
    assert age_h < limit_h, (
        f"STALE: regime_state.json is {age_h:.1f}h old "
        f"(limit: {limit_h}h). Run Marcus pipeline."
    )
    return data


def _fetch_risk_free_rate() -> float:
    """Fetch DTE-matched risk-free rate from FRED. Falls back to 0.045 if unavailable."""
    try:
        import requests
        fred_key = os.environ.get('FRED_API_KEY')
        if not fred_key:
            raise ValueError("FRED_API_KEY not set")
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={FRED_RISK_FREE_SERIES}&api_key={fred_key}"
            f"&file_type=json&sort_order=desc&limit=1"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        obs = resp.json()['observations']
        rate = float(obs[0]['value']) / 100.0
        logger.info("Risk-free rate from FRED ({}): {:.3f}", FRED_RISK_FREE_SERIES, rate)
        return rate
    except Exception as e:
        fallback = 0.045
        logger.warning("FRED rate fetch failed ({}). Using fallback {:.3f}", e, fallback)
        return fallback


def _get_iv_history(ticker: str, days: int = 252) -> 'pd.Series':
    """Pull ATM IV history from trading.db for IVR/IVP calculation."""
    import pandas as pd
    try:
        conn = get_connection(VOL_DB_PATH)
        df = conn.execute(
            "SELECT date, atm_iv_30d FROM vol_signals "
            "WHERE ticker = ? AND atm_iv_30d IS NOT NULL "
            "ORDER BY date DESC LIMIT ?",
            [ticker, days]
        ).df()
        conn.close()
        return pd.Series(df['atm_iv_30d'].values) if not df.empty else pd.Series([], dtype=float)
    except Exception:
        import pandas as pd
        return pd.Series([], dtype=float)


def _get_price_history(ticker: str, days: int = 30) -> 'pd.Series':
    """Pull spot price history from yfinance for RV calculation."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{days+5}d")
        return hist['Close'].tail(days + 2)
    except Exception as e:
        import pandas as pd
        logger.warning("{}: price history fetch failed — {}", ticker, e)
        return pd.Series([], dtype=float)


def _process_ticker(ticker: str, today: str, rate: float,
                    spot_vix: 'float | None', macro_regime: str,
                    max_exp: int) -> 'dict | None':
    """Run Stage 1 for one ticker. Returns the signals dict (also written to
    vol_signals), or None if the ticker failed (caller appends to `failures`).

    Pure extraction of the former inline loop body — no behaviour change other
    than stamping next_earnings_date and data_source onto the row. Keeping it
    module-level (not a closure) lets the UW backfill reuse the same per-ticker
    pipeline if it ever needs to refresh a single name live.
    """
    try:
        chain_result = fetch_options_chain(ticker, rate, max_expirations=max_exp)
        if chain_result is None:
            return None

        spot      = chain_result['spot']
        div_yield = chain_result['div_yield']
        chains    = chain_result['chains']

        # Term structure
        ts_dict = build_term_structure(chains, spot, rate)
        ts_signals = term_structure_slopes(ts_dict) if len(ts_dict) >= 2 else {}
        atm_iv_30d = ts_signals.get('iv_30')

        # Forward price — computed from inputs, NOT from ts_dict
        # (ts_dict maps {dte: atm_iv}; ts_dict.get(30) is an IV, not a price)
        fwd_30d = forward_price(spot, rate, div_yield, 30)

        # Skew — nearest expiration with both calls and puts
        skew_signals = {}
        skew_by_delta = {}
        for exp_key_c in sorted(k for k in chains if k.endswith('_c')):
            exp_key_p = exp_key_c.replace('_c', '_p')
            if exp_key_p in chains:
                skew_signals = extract_skew_slice(chains[exp_key_c], chains[exp_key_p])
                skew_by_delta = extract_skew_by_delta(chains[exp_key_c], chains[exp_key_p])
                break

        # P/C open-interest ratios (aggregate + per expiration)
        pc_oi_ratios = compute_pc_oi_ratios(chains)

        # Full strike × expiration surface → vol_surface table
        surface_rows = upsert_vol_surface(ticker, today, chains)

        # IVR/IVP
        iv_hist = _get_iv_history(ticker)
        vix_for_bias = spot_vix or (atm_iv_30d or 18.0)
        ivr_data = iv_context(
            atm_iv_30d or 0.0, iv_hist, vix_for_bias,
            min_history_days=VOL_IVR_MIN_HISTORY_DAYS,
        )

        # VRP proxy
        price_hist = _get_price_history(ticker)
        vrp_data = {}
        if atm_iv_30d and len(price_hist) >= 22:
            vrp_data = backward_vrp_proxy(atm_iv_30d, price_hist)

        signals = {
            'ticker':         ticker,
            'date':           today,
            'spot_price':     spot,
            'forward_price':  fwd_30d,          # ← corrected from v1.0
            'risk_free_rate': rate,
            'div_yield':      div_yield,
            'atm_iv_30d':     atm_iv_30d,
            'iv_rank':        ivr_data.get('iv_rank'),
            'iv_percentile':  ivr_data.get('iv_percentile'),
            'ivr_ivp_confidence': ivr_data.get('confidence'),
            'ivr_regime_bias':    ivr_data.get('regime_bias'),
            'skew_25d_rr':    skew_signals.get('skew_25d_rr'),
            'skew_25d_put':   skew_signals.get('skew_25d_put'),
            'skew_25d_call':  skew_signals.get('skew_25d_call'),
            'skew_1025_ratio': skew_signals.get('skew_1025_ratio'),
            'ts_iv_30d':      ts_signals.get('iv_30'),
            'ts_iv_60d':      ts_signals.get('iv_60'),
            'ts_iv_180d':     ts_signals.get('iv_180'),
            'ts_front_slope': ts_signals.get('front_slope'),
            'ts_back_slope':  ts_signals.get('back_slope'),
            'ts_shape':       ts_signals.get('ts_shape'),
            'rv_21d':         vrp_data.get('rv_21d'),
            'vrp_proxy_bkwd': vrp_data.get('vrp_proxy_bkwd'),
            'vrp_proxy_signal': vrp_data.get('vrp_proxy_signal'),
            'macro_regime':   macro_regime,
            # Stamped at run time so the batch-compare earnings flag and any
            # provenance filter are pure DB reads (no yfinance in the read path).
            'next_earnings_date': next_earnings_date(ticker),
            'term_structure_json': ts_dict,
            'skew_by_delta_json':  skew_by_delta,
            'pc_oi_ratio_json':    pc_oi_ratios,
            'data_source':        'yfinance',
        }

        upsert_vol_signals(signals)
        logger.info(
            "{}: OK — ATM IV 30d: {}, ts_shape: {}, fwd_30d: {:.2f}, "
            "surface rows: {}",
            ticker, atm_iv_30d, ts_signals.get('ts_shape'), fwd_30d,
            surface_rows
        )
        return signals

    except Exception as e:
        logger.error("{}: processing failed — {}", ticker, e)
        return None


def run_daily_vol(tickers: "list[str] | None" = None,
                  skip_regime_check: bool = False) -> dict:
    """
    Run the full vol pipeline. Returns summary dict.
    Raises AssertionError if prerequisites are not met.

    tickers:
        None (default) → the configured daily universe (`sarah.vol_tickers`).
        This is the scheduled path and is unchanged.
        A list → BATCH MODE: run exactly those tickers instead. Used by the
        RCS trade intake seam (a trade on a ticker outside the daily universe
        has no vol_signals rows until this runs) and by ad-hoc screening.
        Batch results persist to trading.db exactly like the daily run — they
        accumulate IV-rank history and appear in the vol monitor, which is
        intentional.

    skip_regime_check:
        Relax the regime_state.json AGE gate for screening runs (see
        _load_regime_state). The file is still required.

    Batch mode deliberately does NOT write data/outputs/vol_signals.json:
    that file is the "last daily run" context snapshot consumed by
    /api/context/vol-signals, and a two-ticker intake batch must not
    overwrite the day's full-universe picture. trading.db is the source of
    truth for every comparison read.
    """
    batch_mode = tickers is not None
    if batch_mode:
        # Normalise: uppercase, de-duplicate, preserve caller order.
        seen, run_tickers = set(), []
        for t in tickers:
            t = str(t).strip().upper()
            if t and t not in seen:
                seen.add(t)
                run_tickers.append(t)
        assert run_tickers, "tickers list is empty — nothing to run"
    else:
        run_tickers = list(VOL_TICKERS)

    logger.info("=== Vol Run starting ({}) — {} ticker(s): {} ===",
                "batch" if batch_mode else "daily", len(run_tickers),
                ", ".join(run_tickers))

    regime_data = _load_regime_state(skip_staleness_check=skip_regime_check)
    macro_regime = regime_data['regime_state']
    logger.info("Regime: {}", macro_regime)

    initialize_vol_schema()  # idempotent

    rate = _fetch_risk_free_rate()

    vix_ts = fetch_vix_term_structure()
    spot_vix = vix_ts['spot_vix'] if vix_ts else None

    fetch_vvix_daily()  # idempotent — stores in vvix_daily table in trading.db

    today = datetime.date.today().isoformat()
    all_ticker_signals = {}
    failures = []

    max_exp = get_params("sarah").chain_max_expirations
    delay = get_params("sarah").batch_inter_ticker_delay_s if batch_mode else 0.0

    for i, ticker in enumerate(run_tickers):
        if delay and i:
            logger.info("batch pacing — sleeping {:.1f}s before {}", delay, ticker)
            time.sleep(delay)
        logger.info("Processing {}", ticker)
        sig = _process_ticker(ticker, today, rate, spot_vix, macro_regime, max_exp)
        if sig is None:
            failures.append(ticker)
            continue
        all_ticker_signals[ticker] = sig

    output = {
        'as_of':        today,
        'written_at':   datetime.datetime.now().isoformat(),
        'macro_regime': macro_regime,
        'data_warning': '⚠ yfinance 15–20 min delayed. Not for live pre-trade decisions.',
        'signals':      {
            t: {
                'atm_iv_30d':       s.get('atm_iv_30d'),
                'rv_21d':           s.get('rv_21d'),
                'vrp_proxy_bkwd':   s.get('vrp_proxy_bkwd'),
                'vrp_proxy_signal': s.get('vrp_proxy_signal'),
                'vrp_note':         'backward-looking 21d RV vs 30d IV — not matched-maturity VRP',
                'skew_25d_rr':      s.get('skew_25d_rr'),
                'iv_rank':          s.get('iv_rank'),
                'iv_percentile':    s.get('iv_percentile'),
                'ivr_confidence':   s.get('ivr_ivp_confidence'),
                'ts_front_slope':   s.get('ts_front_slope'),
                'ts_back_slope':    s.get('ts_back_slope'),
                'ts_shape':         s.get('ts_shape'),
                'vol_regime':       _classify_vol_regime(s.get('atm_iv_30d'), spot_vix),
            }
            for t, s in all_ticker_signals.items()
        },
        'failures': failures,
        'batch_mode': batch_mode,
        'requested_tickers': run_tickers,
    }

    if batch_mode:
        logger.info(
            "batch mode — vol_signals.json NOT overwritten (it is the daily "
            "run's context snapshot); results are in trading.db")
    else:
        out_path = Path(OUTPUTS_DIR) / 'vol_signals.json'
        out_path.write_text(json.dumps(output, indent=2, default=str))
        logger.info("vol_signals.json written to {}", out_path)
    logger.info(
        "=== Vol Run complete ({}) — {} tickers, {} failures{} ===",
        "batch" if batch_mode else "daily",
        len(all_ticker_signals), len(failures),
        f" ({', '.join(failures)})" if failures else ""
    )

    # VVIX is fetched once above (line ~137) via the module-level import.
    # A prior "Stage 5" block re-imported fetch_vvix_daily locally here, which
    # made the name function-local for the whole body and raised
    # UnboundLocalError at the earlier call. Removed — do not re-add a local
    # import of fetch_vvix_daily inside this function.

    return output


def _classify_vol_regime(atm_iv: float | None, spot_vix: float | None) -> str:
    ref = spot_vix or atm_iv or 18.0
    if ref < 15:   return 'LOW_VOL'
    elif ref < 20: return 'NORMAL_VOL'
    elif ref < 30: return 'ELEVATED_VOL'
    else:          return 'HIGH_VOL'


if __name__ == '__main__':
    import sys
    cli_tickers = [a.upper() for a in sys.argv[1:] if not a.startswith('-')]
    result = run_daily_vol(
        tickers=cli_tickers or None,
        skip_regime_check='--skip-regime-check' in sys.argv,
    )
    print(json.dumps(
        {k: v for k, v in result.items() if k != 'signals'},
        indent=2, default=str
    ))
