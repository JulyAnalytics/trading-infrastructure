# systems/sarah/catalyst_calendar.py
"""
U4.3 — Automated catalyst calendar integration
(spec: sarah_vol_upgrade_path_stages_4_5_v2.md §U4.3).

Auto-resolves catalyst_type and thesis_days for the pre-trade memo builder
from two free sources:
  - earnings dates: yfinance Ticker.calendar
  - macro events (FOMC, CPI, payrolls, …): the macro_calendar table that
    Marcus's fetch_calendar_data() already maintains in macro.db

The trader confirms or overrides — this removes the lookup, not the judgment.
Edge cases per spec: multiple upcoming events → all candidates surfaced for
confirmation; nothing found → requires_manual with a warning.
"""
from __future__ import annotations

import datetime

from loguru import logger

from config import DUCKDB_PATH
from systems.utils.db import get_connection

# Macro events important enough to be a trade catalyst (importance 1 in
# macro_calendar: FOMC, CPI, PCE, payrolls).
_MACRO_IMPORTANCE_MAX = 1


def _earnings_candidates(ticker: str, today: datetime.date) -> list[dict]:
    """Next earnings date via yfinance. Returns [] on any failure — earnings
    lookup must never block the memo builder."""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        dates = []
        if isinstance(cal, dict):
            raw = cal.get('Earnings Date') or []
            dates = raw if isinstance(raw, (list, tuple)) else [raw]
        elif cal is not None and hasattr(cal, 'index') and 'Earnings Date' in cal.index:
            dates = list(cal.loc['Earnings Date'])
        out = []
        for d in dates:
            d = d.date() if hasattr(d, 'date') else d
            if isinstance(d, datetime.date) and d > today:
                out.append({
                    'event':         'earnings',
                    'date':          d.isoformat(),
                    'catalyst_type': 'event_specific',
                    'thesis_days':   (d - today).days + 1,
                    'source':        'yfinance',
                })
        return out[:1]  # nearest upcoming earnings only
    except Exception as e:
        logger.warning("{}: earnings calendar lookup failed — {}", ticker, e)
        return []


def _macro_candidates(today: datetime.date, days_ahead: int = 60,
                      conn=None) -> list[dict]:
    """Upcoming importance-1 events from macro_calendar (FOMC/CPI/PCE/NFP).

    Pass an open (read-only is fine) macro.db connection via `conn` to reuse
    one from an API request; otherwise a short-lived one is opened.
    """
    own = conn is None
    if own:
        conn = get_connection(DUCKDB_PATH)
    try:
        rows = conn.execute("""
            SELECT event_name, event_date FROM macro_calendar
            WHERE event_date > ? AND event_date <= ? AND importance <= ?
            ORDER BY event_date
        """, [today, today + datetime.timedelta(days=days_ahead),
              _MACRO_IMPORTANCE_MAX]).fetchall()
    except Exception as e:
        logger.warning("macro_calendar lookup failed — {}", e)
        return []
    finally:
        if own:
            conn.close()

    out = []
    for name, d in rows:
        d = d if isinstance(d, datetime.date) else datetime.date.fromisoformat(str(d)[:10])
        out.append({
            'event':         name,
            'date':          d.isoformat(),
            'catalyst_type': 'macro_catalyst',
            'thesis_days':   (d - today).days + 1,
            'source':        'macro_calendar',
        })
    return out


def resolve_catalyst(ticker: str, macro_conn=None) -> dict:
    """
    Auto-resolve catalyst candidates for a ticker. Returns:
      {'primary': {...}, 'all_candidates': [...], 'requires_manual': False}
    or, when nothing is scheduled:
      {'catalyst_type': None, 'thesis_days': None, 'requires_manual': True,
       'note': ...}
    """
    today = datetime.date.today()
    candidates = _earnings_candidates(ticker, today) + _macro_candidates(
        today, conn=macro_conn)

    if not candidates:
        return {
            'ticker': ticker,
            'catalyst_type': None,
            'thesis_days': None,
            'requires_manual': True,
            'note': ('No upcoming earnings or importance-1 macro events found. '
                     'Enter catalyst_type manually. If macro_calendar is empty, '
                     'run the fred_incremental job.'),
        }

    candidates.sort(key=lambda c: c['date'])
    return {
        'ticker':          ticker,
        'primary':         candidates[0],
        'all_candidates':  candidates,
        'requires_manual': False,
        'note': ('Primary = nearest upcoming event. Confirm it matches your '
                 'actual thesis catalyst before accepting the pre-filled '
                 'catalyst_type / thesis_days.'),
    }


def next_earnings_date(ticker: str, today: datetime.date | None = None) -> str | None:
    """Nearest upcoming earnings iso-date for `ticker`, or None.

    Stamped onto vol_signals.next_earnings_date at run time so the batch-compare
    earnings flag is a pure DB read (no yfinance call in the read path). Never
    raises — earnings lookup is best-effort and must never block the pipeline.
    """
    today = today or datetime.date.today()
    cands = _earnings_candidates(ticker, today)
    return cands[0]['date'] if cands else None


def has_near_term_catalyst(ticker: str, days: int = 14,
                           today: datetime.date | None = None,
                           macro_conn=None) -> bool:
    """True if `ticker` has earnings or an importance-1 macro event within
    `days` calendar days of `today`. Used to flag the earnings row in the
    batch-compare table without a per-row network call.
    """
    today = today or datetime.date.today()
    cutoff = today + datetime.timedelta(days=days)

    earnings = _earnings_candidates(ticker, today)
    if earnings:
        try:
            ed = datetime.date.fromisoformat(earnings[0]['date'][:10])
            if ed <= cutoff:
                return True
        except (ValueError, KeyError, TypeError):
            pass

    for c in _macro_candidates(today, days_ahead=days, conn=macro_conn):
        try:
            md = datetime.date.fromisoformat(str(c['date'])[:10])
            if md <= cutoff:
                return True
        except (ValueError, KeyError, TypeError):
            continue
    return False
