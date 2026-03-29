# $0 Self-Built Stack & Build Sequence

---

## The Honest Gap Assessment

Before the architecture, it's worth naming where $0 genuinely can't get you there:

**Real ceilings:**
- **Real-time OPRA feed** — there is no free substitute for live options quotes at the full chain level. You can get delayed (15–20 min) for free, but for execution that's not usable
- **OptionMetrics Ivy DB** — the historical vol surface data is genuinely irreplaceable for serious backtest work. Free alternatives are thinner and less clean
- **Bloomberg** — you can replicate maybe 70% of what you'd use it for, but the remaining 30% (particularly cross-asset real-time data and the terminal's analytical tools) has no clean free substitute
- **Counterparty/prime brokerage analytics** — these come with relationships, not purchases

Everything else? Surprisingly buildable.

---

## The $0 Stack by Role

---

### Data Foundation First

**Market Data**
- **yfinance** — free, Python-native, covers equities/ETFs/indices/basic options chains with 15-min delay. Unreliable for production but fine for research
- **Polygon.io free tier** — 15-min delayed quotes, solid API, good historical data going back years. The $29/month starter tier is the first dollar genuinely worth spending
- **CBOE free data** — VIX history, VIX futures settlement, options volume data. Legitimately useful and free
- **Nasdaq Data Link (Quandl) free tier** — hundreds of free datasets including futures, some macro, some alternative data
- **Alpha Vantage free tier** — equities, FX, some crypto. Rate-limited but usable for research

**Options-Specific**
- **yfinance options chains** — delayed but covers strikes, expiration, IV, Greeks for most liquid underlyings. Good enough for strategy research, not for execution
- **CBOE historical options data** — free downloads of end-of-day options data going back years. Underutilized and genuinely valuable for backtest work
- **Thinkorswim (TD Ameritrade/Schwab)** — paper trading platform gives you a real-time options chain, vol surface visualization, and Greeks for free if you open an account. No capital required for paper trading. This is a significant unlock
- **tastytrade** — free platform with excellent options analytics, IV rank/percentile, vol surface visualization. Analytically solid

**Macro & Economic**
- **FRED API** — the entire Federal Reserve Economic Database, free, excellent API, covers essentially everything Marcus needs for US macro
- **World Bank API** — free international macro data
- **BLS and BEA APIs** — free employment, inflation, GDP data direct from source
- **CFTC COT data** — free weekly positioning data, downloadable or via API wrappers

**Alternative & Positioning**
- **AAII sentiment survey** — free weekly retail sentiment
- **Fear & Greed Index (CNN)** — scrapeable
- **Put/call ratio** — CBOE publishes this free daily
- **Short interest data** — FINRA publishes twice monthly for free

---

### Core Infrastructure

**Time Series Database**
- **TimescaleDB** — free open source, runs on PostgreSQL, handles financial time series well. Run locally or on a free-tier cloud instance
- **DuckDB** — newer, increasingly popular for analytical queries on financial data. Runs in-process, no server needed, handles parquet files natively. Excellent for research workflows

**Compute & Notebooks**
- **Google Colab** — free GPU/CPU compute, Jupyter environment, persistent storage via Google Drive. Sufficient for most research workloads
- **VS Code + local Jupyter** — for anything needing local data access
- **GitHub** — free for version control, research notebook storage, data pipeline code

**Data Pipeline**
- **Python + pandas + schedule library** — simple cron-style data fetching and storage, sufficient for boutique scale
- **Apache Airflow** — free open source for more sophisticated pipeline orchestration
- **Prefect** — free tier, more user-friendly than Airflow for solo builders

**Portfolio Database**
- **PostgreSQL** — free, run locally or on Supabase free tier
- **Supabase** — free hosted PostgreSQL with a decent dashboard

---

### Role-Specific Free Stacks

**Sarah Chen — Vol & Derivatives**

- **Thinkorswim paper trading** — real-time options chains, vol surface (thinkBack for historical), Greeks, P&L simulation. The most powerful free options tool available. Professional traders use this for analysis even when they execute elsewhere
- **py_vollib** — Python options pricing library, Black-Scholes and binomial, free
- **QuantLib (Python bindings)** — open source standard for derivatives pricing. Steep learning curve but genuinely institutional quality
- **vollib + volsurface** — Python libraries for vol surface construction and interpolation
- **CBOE VIX data + term structure** — free, covers the core of what Marcus and Sarah need for regime classification
- **SpotGamma free content** — their paid product is valuable but free daily notes and GEX methodology explanations are enough to build a basic dealer positioning proxy

*The real ceiling:* Real-time full-chain OPRA data for execution. For research and strategy development, the free stack is legitimately close to professional grade.

---

**Marcus Webb — Macro Strategist**

This is the role where $0 gets closest to professional grade — macro data is predominantly public.

- **FRED API + fredapi Python library** — covers essentially everything. 800,000+ data series
- **pandas-datareader** — unified API for FRED, World Bank, OECD, Fama-French data
- **investpy** — free access to investing.com data including bonds, indices, macro indicators globally
- **Quandl free tier** — futures data, some macro
- **TradingView free tier** — excellent cross-asset charting, macro overlays. The free tier is genuinely capable
- **CFTC COT via Quandl or direct download** — free positioning data
- **BIS (Bank for International Settlements)** — free global financial stability data, underutilized
- **IMF Data API** — free global macro

*The real ceiling:* Real-time cross-asset data and Bloomberg's analytical depth. For strategic macro analysis, the free stack is 85%+ of professional capability.

---

**Priya Nair — Quantitative Researcher**

The open source quant stack is genuinely world-class now.

- **Zipline Reloaded** — maintained fork of the original Quantopian backtesting engine, free, handles equities well
- **bt (backtesting library)** — more flexible than Zipline for custom strategies
- **Backtrader** — good for strategy-level backtesting, handles options better than Zipline
- **VectorBT** — newer, vectorized backtesting, significantly faster than Backtrader for parameter sweeps. Genuinely excellent
- **QuantLib Python** — options backtesting, derivatives pricing
- **statsmodels** — time series analysis, regime detection, statistical testing
- **scikit-learn** — ML for signal research
- **MLflow free tier** — experiment tracking, keeps research reproducible
- **Alphalens (open source)** — factor analysis framework, free
- **PyFolio (open source)** — portfolio performance analysis, free
- **CBOE end-of-day options history** — the key free dataset for options backtesting

*The real ceiling:* OptionMetrics Ivy DB for clean historical vol surfaces. For equity strategies, the free stack is very close to professional. For serious options backtesting, you'll feel the gap.

---

**Jordan Okafor — Risk Manager**

Risk infrastructure is very buildable for free because it's primarily computation on data you already have.

- **QuantLib Python** — Greeks calculation, risk metrics, scenario analysis
- **PyPortfolioOpt** — portfolio optimization and risk metrics, free
- **Riskfolio-Lib** — more sophisticated portfolio risk analysis, free, underrated
- **empyrical (open source)** — performance and risk metrics library from Quantopian, free
- **OpenGamma Strata** — open source risk analytics from a serious vendor, Java-based but Python wrappers exist. Institutional quality, genuinely free
- **Custom stress testing** — Python + historical data. Apply 2008, 2020, 2018 scenarios to current positions. No commercial tool needed
- **Grafana free tier** — dashboarding for real-time risk monitoring, connects to your PostgreSQL database

*The real ceiling:* Real-time Greeks aggregation at speed. For a small book, Python is fast enough. As position count grows, you'll want something faster.

---

**Kai Tanaka — Execution**

This role has the hardest $0 ceiling because execution quality requires a live brokerage relationship.

- **Interactive Brokers** — free to open, lowest commissions in the industry, solid API (ib_insync Python library). The only cost is capital
- **ib_insync** — Python library for IBKR API, free, well-maintained. Handles real-time quotes, order management, position tracking
- **IBKR paper trading** — full API access, real-time data, no capital required. For strategy testing and architecture development, this is effectively a free professional execution environment
- **Custom TCA in Python** — track every fill against arrival price, build your own slippage analysis
- **Lumibot** — free algorithmic trading framework, connects to IBKR and others

*The real ceiling:* Capital and relationships, not tools. The IBKR free infrastructure is legitimately professional grade.

---

**Sam Reyes — COO / Portfolio Analyst**

- **Notion free tier** — knowledge base, strategy documentation, process documentation
- **Google Sheets** — portfolio tracking, P&L attribution, investor reporting at early stage
- **Beancount** — open source double-entry accounting, used by some boutique funds
- **GitHub** — version control for all code, research, and pipeline infrastructure
- **Grafana + PostgreSQL** — free reporting dashboard layer
- **Pandoc + Python** — automated report generation from templates

*The real ceiling:* Compliance infrastructure and serious portfolio accounting (Advent Geneva) have no good free substitutes. For early stage this matters less. When you have external capital, this is where you need to spend.

---

## The Full $0 Architecture

```
DATA LAYER
├── Free Market Data
│   ├── yfinance / Polygon free tier (equities, ETFs)
│   ├── CBOE free data (VIX, options EOD, put/call)
│   ├── FRED API (macro, rates, economic)
│   ├── CFTC COT (positioning)
│   └── Nasdaq Data Link free (futures, alternative)
│
├── Time Series Storage
│   ├── DuckDB (analytical queries, local)
│   └── PostgreSQL / Supabase free (persistent storage)
│
└── Data Pipeline
    └── Python + schedule / Prefect free tier

RESEARCH LAYER
├── Priya: VectorBT + QuantLib + Alphalens + MLflow
├── Sarah: py_vollib + QuantLib + Thinkorswim
├── Marcus: FRED + pandas-datareader + TradingView free
└── Jordan: Riskfolio-Lib + OpenGamma + empyrical

EXECUTION LAYER
├── IBKR paper → live (ib_insync Python API)
├── Thinkorswim (analysis + paper trading)
└── Custom TCA in Python

MONITORING LAYER
├── Grafana free (dashboards → PostgreSQL)
├── Custom Greeks aggregation (Python + QuantLib)
└── Jupyter notebooks (research + review)

OPERATIONS LAYER
├── Notion (knowledge base, strategy docs)
├── GitHub (code, research, version control)
├── Google Sheets (P&L, reporting)
└── Google Colab (heavy compute)
```

---

## The First Dollar Spent

When budget opens up, highest-leverage first purchases in order:

1. **Polygon.io starter ($29/mo)** — unlocks real-time data, meaningfully upgrades Kai and Sarah's work
2. **CBOE historical options data subscription** — fills the biggest gap in Priya's backtest capability
3. **One Bloomberg terminal access** — via a university library, shared workspace, or terminal lite. Gets Marcus and Sarah the cross-asset real-time layer
4. **IBKR funded account** — the execution infrastructure is already free, capital is what activates it

---

## The Honest Summary

| Domain | $0 Capability vs. Professional |
|---|---|
| Research & strategy development | ~75–80% |
| Macro analysis | ~85–90% |
| Live execution (tools) | ~95% — constraint is capital, not software |
| Compliance & portfolio accounting | Genuinely breaks down — last thing you need pre-external capital |

The architecture is genuinely buildable. The sequencing question is: build the data layer and research infrastructure first, validate strategies in paper trading, then invest in data quality as live performance justifies it.

---

# The Build Sequence

---

## Phase 0: Foundation
**Goal: One place where data lives and code runs**
**Time: 1–2 days**

The only phase where you build nothing useful yet — but skipping it means rebuilding everything later.

### 1. Environment Setup
```
- Python 3.11+ with pyenv (manage versions cleanly)
- Virtual environment per project (venv or conda)
- VS Code with Jupyter extension
- Git + GitHub repo: "trading-infrastructure"
```

### 2. Directory Structure
```
trading-infrastructure/
├── data/
│   ├── raw/          # exactly as downloaded, never modified
│   ├── processed/    # cleaned, normalized
│   └── cache/        # temporary, regenerable
├── research/
│   ├── signals/      # individual signal notebooks
│   ├── strategies/   # strategy-level research
│   └── archive/      # killed ideas, kept for reference
├── systems/
│   ├── data_feeds/   # ingestion scripts
│   ├── risk/         # Greeks, portfolio risk
│   └── execution/    # IBKR connection
├── reports/          # weekly review outputs
└── docs/             # Notion mirror for key decisions
```

### 3. Database
```bash
pip install duckdb
# Install PostgreSQL via Supabase free tier or locally
```

### 4. Core Python Libraries
```bash
pip install yfinance pandas numpy scipy \
  statsmodels scikit-learn matplotlib \
  plotly duckdb psycopg2 python-dotenv \
  requests fredapi pandas-datareader
```

**Commit everything. You now have a clean foundation.**

---

## Phase 1: Marcus's Macro Layer
**Goal: Regime classification running on real data**
**Time: 3–5 days**

Build Marcus first because his output — regime state — is the context everything else operates within.

### 1. FRED Data Pipeline
```python
# systems/data_feeds/macro_feed.py

from fredapi import Fred
import duckdb
import pandas as pd

fred = Fred(api_key='your_free_api_key')

MACRO_SERIES = {
    'fed_funds': 'FEDFUNDS',
    'treasury_10y': 'GS10',
    'treasury_2y': 'GS2',
    'yield_curve': 'T10Y2Y',
    'vix': 'VIXCLS',
    'credit_spread': 'BAMLH0A0HYM2',
    'inflation': 'CPIAUCSL',
    'unemployment': 'UNRATE',
    'nfp': 'PAYEMS',
}

def fetch_and_store():
    conn = duckdb.connect('data/processed/macro.db')
    for name, series_id in MACRO_SERIES.items():
        df = fred.get_series(series_id)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {name}
            (date DATE, value FLOAT)
        """)
        # upsert logic here
```

### 2. Regime Classifier
```python
# research/signals/regime_classifier.py

def classify_regime(vix, yield_curve, hy_spread, sp500_trend):
    if vix > 25 and hy_spread > 500:
        return 'RISK_OFF_STRESS'
    elif vix > 20 or yield_curve < 0:
        return 'CAUTION'
    elif vix < 15 and yield_curve > 50:
        return 'RISK_ON_LOW_VOL'
    else:
        return 'NEUTRAL'
```

### 3. Macro Dashboard

Build a single page showing:
- Current regime classification
- VIX level and 30/90/180 day history
- Yield curve shape
- Credit spreads
- CFTC COT positioning for key instruments

**Deliverable: A regime state that updates daily and is queryable by every other system.**

---

## Phase 2: Sarah's Vol Surface Layer
**Goal: Vol surface visualization and basic signal extraction**
**Time: 5–7 days**

### 1. Options Data Pipeline
```python
# systems/data_feeds/options_feed.py
import yfinance as yf

def fetch_options_chain(ticker='SPY'):
    stock = yf.Ticker(ticker)
    expirations = stock.options

    chains = {}
    for exp in expirations[:6]:  # nearest 6 expirations
        opt = stock.option_chain(exp)
        chains[exp] = {
            'calls': opt.calls,
            'puts': opt.puts
        }
    return chains
```

### 2. Vol Surface Construction
```python
# research/signals/vol_surface.py
from py_vollib.black_scholes.implied_volatility import implied_volatility

def build_surface(chain, spot, rate=0.05):
    surface = []
    for exp, data in chain.items():
        dte = calculate_dte(exp)
        for _, row in data['puts'].iterrows():
            if row['bid'] > 0 and row['ask'] > 0:
                mid = (row['bid'] + row['ask']) / 2
                moneyness = row['strike'] / spot
                try:
                    iv = implied_volatility(
                        mid, spot, row['strike'],
                        dte/365, rate, 'p'
                    )
                    surface.append({
                        'dte': dte,
                        'moneyness': moneyness,
                        'strike': row['strike'],
                        'iv': iv,
                        'volume': row['volume'],
                        'oi': row['openInterest']
                    })
                except:
                    pass
    return pd.DataFrame(surface)
```

### 3. Key Signals to Extract Daily
```python
# Signals to extract daily and store:
# 1. ATM IV by expiration (term structure)
# 2. 25-delta put skew (downside fear)
# 3. VIX vs realized vol spread (VRP proxy)
# 4. Put/call OI ratio by expiration
# 5. IV rank and IV percentile (last 252 days)

def iv_rank(current_iv, iv_history):
    return (current_iv - iv_history.min()) / \
           (iv_history.max() - iv_history.min())

def iv_percentile(current_iv, iv_history):
    return (iv_history < current_iv).mean()
```

**Deliverable: Daily vol surface snapshots stored in DuckDB, key vol signals queryable, regime-conditional vol analysis possible.**

---

## Phase 3: Priya's Research Framework
**Goal: Reproducible backtesting infrastructure**
**Time: 7–10 days**

Don't build strategies yet. Build the framework that tests them honestly.

### 1. Install Research Stack
```bash
pip install vectorbt quantlib-python \
  pyfolio-reloaded alphalens-reloaded \
  mlflow backtrader bt
```

### 2. Backtest Framework with Options Reality
```python
# systems/backtest/options_backtester.py

class OptionsBacktester:
    """
    Key principles baked in:
    - Uses bid/ask mid, not last price
    - Applies configurable slippage assumption
    - Tracks Greeks through the trade lifecycle
    - Flags when liquidity assumptions are unrealistic
    - Separates realized vol from implied vol P&L
    """

    def __init__(self, slippage_bps=50, min_volume=100):
        self.slippage = slippage_bps / 10000
        self.min_volume = min_volume

    def can_execute(self, row):
        if row['volume'] < self.min_volume:
            return False, "Insufficient volume"
        if row['ask'] / row['bid'] > 1.10:
            return False, "Spread too wide (>10%)"
        return True, "OK"

    def fill_price(self, bid, ask, direction):
        mid = (bid + ask) / 2
        if direction == 'buy':
            return mid * (1 + self.slippage)
        else:
            return mid * (1 - self.slippage)
```

### 3. Research Notebook Template

Every signal/strategy notebook follows this structure:

```
1. HYPOTHESIS
   - What edge am I testing?
   - Why should this edge exist? (mechanism)
   - What regime should it work in?

2. DATA
   - Source and date range
   - Known limitations of this data
   - Survivorship bias notes

3. SIGNAL CONSTRUCTION
   - Exact calculation, reproducible
   - No look-ahead bias check

4. BACKTEST
   - Entry/exit rules
   - Position sizing
   - Transaction cost assumptions (conservative)
   - Benchmark

5. RESULTS
   - Returns, Sharpe, max drawdown
   - Regime-conditional breakdown (critical)
   - Stress periods: 2018, 2020, 2022

6. RED FLAGS
   - What this backtest doesn't capture
   - What would kill this in production

7. VERDICT
   - Go / No-go / Needs more research
```

### 4. MLflow Experiment Tracking
```python
import mlflow

with mlflow.start_run(run_name="short_straddle_v3"):
    mlflow.log_params({
        'dte_entry': 45,
        'dte_exit': 21,
        'delta_hedge': True,
        'slippage_bps': 50
    })
    mlflow.log_metrics({
        'sharpe': 1.24,
        'max_drawdown': -0.18,
        'win_rate': 0.68,
        'avg_pnl_per_trade': 142
    })
```

**Deliverable: Every strategy idea goes through this framework before anyone discusses it seriously. Research is reproducible and tracked.**

---

## Phase 4: Jordan's Risk Layer
**Goal: Portfolio-level risk monitoring**
**Time: 5–7 days**

### 1. Greeks Aggregation
```python
# systems/risk/greeks_aggregator.py
import QuantLib as ql

class PortfolioRiskEngine:

    def __init__(self):
        self.positions = []

    def add_position(self, ticker, strike, expiry,
                     option_type, quantity, spot, vol, rate):
        greeks = self.calculate_greeks(
            spot, strike, expiry, vol, rate, option_type
        )
        self.positions.append({
            'ticker': ticker,
            'quantity': quantity,
            'delta': greeks['delta'] * quantity,
            'gamma': greeks['gamma'] * quantity,
            'vega': greeks['vega'] * quantity,
            'theta': greeks['theta'] * quantity,
        })

    def portfolio_greeks(self):
        return {
            'net_delta': sum(p['delta'] for p in self.positions),
            'net_gamma': sum(p['gamma'] for p in self.positions),
            'net_vega': sum(p['vega'] for p in self.positions),
            'net_theta': sum(p['theta'] for p in self.positions),
        }
```

### 2. Risk Limits Framework
```python
RISK_LIMITS = {
    'max_net_delta': 0.20,        # % of portfolio
    'max_net_vega': 0.15,
    'max_single_position': 0.05,  # % of portfolio
    'max_drawdown_alert': 0.08,   # alert at 8%
    'max_drawdown_halt': 0.15,    # halt trading at 15%
    'min_liquidity_days': 5,
}

def check_limits(portfolio_greeks, positions, pnl):
    breaches = []
    if abs(portfolio_greeks['net_delta']) > RISK_LIMITS['max_net_delta']:
        breaches.append('DELTA_BREACH')
    return breaches
```

### 3. Grafana Dashboard

Connect Grafana (free) to your PostgreSQL instance. Build:
- Real-time Greeks by strategy and portfolio total
- P&L vs. drawdown limits
- Regime state from Phase 1 as context
- Alert rules that send to Slack when limits breach

**Deliverable: Greeks aggregated across the book, limit monitoring live, stress tests runnable on demand.**

---

## Phase 5: Kai's Execution Layer
**Goal: IBKR connected, paper trading live**
**Time: 3–5 days**

### 1. IBKR Connection
```bash
pip install ib_insync
```

```python
# systems/execution/ibkr_connector.py
from ib_insync import *

class ExecutionEngine:

    def __init__(self, paper=True):
        self.ib = IB()
        port = 7497 if paper else 7496
        self.ib.connect('127.0.0.1', port, clientId=1)

    def place_order(self, contract, action, quantity):
        order = Order(
            action=action,
            totalQuantity=quantity,
            orderType='LMT',
            lmtPrice=self.get_mid(contract),
            tif='DAY'
        )
        trade = self.ib.placeOrder(contract, order)
        return trade
```

### 2. TCA (Transaction Cost Analysis)
```python
# systems/execution/tca.py

class TCATracker:
    """
    Track every fill against arrival price.
    This is how Kai keeps the backtest honest.
    """

    def record_fill(self, contract, arrival_mid,
                    fill_price, quantity, direction):
        slippage_bps = (
            (fill_price - arrival_mid) / arrival_mid * 10000
            if direction == 'buy'
            else (arrival_mid - fill_price) / arrival_mid * 10000
        )
        self.fills.append({
            'timestamp': datetime.now(),
            'contract': str(contract),
            'arrival_mid': arrival_mid,
            'fill_price': fill_price,
            'slippage_bps': slippage_bps,
            'quantity': quantity
        })

    def report(self):
        df = pd.DataFrame(self.fills)
        return {
            'avg_slippage_bps': df['slippage_bps'].mean(),
            'worst_fill': df['slippage_bps'].max(),
            'total_cost_estimate': (
                df['slippage_bps'] * df['quantity']
            ).sum()
        }
```

### 3. Paper Trade Everything First

Before any live execution, run strategies through IBKR paper for minimum 30 trading days. Track:
- Actual fills vs. backtest assumptions
- Bid/ask as percentage of theoretical edge
- Execution timing vs. vol surface moves

**Deliverable: Full execution loop connected, TCA tracking from day one, paper trading live.**

---

## Phase 6: Alex's Orchestration Layer
**Goal: Weekly review system and prioritization infrastructure**
**Time: 2–3 days**

### 1. Weekly Review Template (Notion)

```
WEEKLY REVIEW — [DATE]
Regime State: [from Marcus]

STRATEGY STATUS
┌─────────────────┬──────────┬─────────┬──────────┐
│ Strategy        │ Status   │ P&L WTD │ Decision │
├─────────────────┼──────────┼─────────┼──────────┤
│ Short straddle  │ Active   │ +$420   │ Keep     │
│ Dispersion v2   │ Research │ n/a     │ Continue │
│ Calendar SPX    │ Paper    │ -$180   │ Watch    │
└─────────────────┴──────────┴─────────┴──────────┘

RESEARCH QUEUE (EV ranked)
1. [Strategy] — EV: 3.2 — Owner: Priya — ETA: 2 weeks
2. [Strategy] — EV: 2.1 — Owner: Sarah — ETA: 1 week
3. [Strategy] — EV: 0.8 — DEFERRED

RISK FLAGS FROM JORDAN
- [Any limit breaches or concerns this week]

NEXT WEEK TOP 3 OUTCOMES
1.
2.
3.
```

### 2. EV Tracker (Airtable free or Google Sheets)

| Strategy Idea | Impact | Probability | Time (hrs) | EV | Status |
|---|---|---|---|---|---|
| Short VRP | 8 | 7 | 40 | 1.4 | Active |
| Dispersion | 9 | 4 | 80 | 0.45 | Backlog |
| 0DTE scalp | 5 | 3 | 20 | 0.75 | Deferred |

### 3. Automated Weekly Report
```python
# reports/weekly_generator.py

def generate_weekly_report():
    regime = get_current_regime()        # Phase 1
    vol_summary = get_vol_summary()      # Phase 2
    strategy_pnl = get_strategy_pnl()   # Phase 5
    risk_flags = get_risk_flags()        # Phase 4

    # Generate markdown report
    # Push to Notion via API
    # Optionally email to yourself
```

**Deliverable: Weekly review runs semi-automatically, research queue is prioritized by EV, decisions are documented.**

---

## Phase 7: Sam's Operations Layer
**Goal: Everything auditable and reportable**
**Time: 3–4 days**

### 1. Trade Log (The Source of Truth)
```python
# Every trade recorded with full context:
{
    'trade_id': 'uuid',
    'timestamp': '2024-01-15T14:32:00',
    'strategy': 'short_straddle_spy',
    'regime_at_entry': 'RISK_ON_LOW_VOL',
    'contract': 'SPY 460P 2024-02-16',
    'action': 'SELL',
    'quantity': 10,
    'fill_price': 3.45,
    'arrival_mid': 3.47,
    'greeks_at_entry': {'delta': -0.25, 'gamma': 0.02},
    'thesis': 'VRP elevated, regime supportive',
    'exit_trigger': 'DTE=21 or 50% profit'
}
```

### 2. P&L Attribution
```python
def attribute_pnl(trade):
    return {
        'delta_pnl': ...,    # directional contribution
        'gamma_pnl': ...,    # convexity contribution
        'vega_pnl': ...,     # vol change contribution
        'theta_pnl': ...,    # time decay contribution
        'total_pnl': ...,
        'vs_backtest': ...   # actual vs. expected
    }
```

### 3. Document Everything in Notion

Three critical pages:
- **Strategy Library** — every strategy ever tested, outcome, why kept/killed
- **Decision Log** — every significant decision with reasoning (your institutional memory)
- **Infrastructure Map** — what's running, where data comes from, what breaks if X goes down

**Deliverable: Every trade is logged, attributed, and auditable. Nothing lives only in someone's head.**

---

## The Full Sequence Summary

| Phase | What You Build | Time | Output |
|---|---|---|---|
| 0 | Environment + structure | 1–2 days | Clean foundation |
| 1 | Marcus: Macro/regime | 3–5 days | Daily regime state |
| 2 | Sarah: Vol surface | 5–7 days | Vol signals + surface |
| 3 | Priya: Research framework | 7–10 days | Backtest infrastructure |
| 4 | Jordan: Risk layer | 5–7 days | Live Greeks + limits |
| 5 | Kai: Execution | 3–5 days | IBKR connected + TCA |
| 6 | Alex: Orchestration | 2–3 days | Weekly review system |
| 7 | Sam: Operations | 3–4 days | Trade log + attribution |

**Total: 29–41 days of focused build time**

---

## The Critical Path

If you had to cut scope, build in this order and stop when it's functional:

**Phase 0 → 1 → 3 → 5** gives you: regime context, honest backtesting, and live execution. That's a functional trading system. Everything else makes it better, more sustainable, and more scalable — but those four phases are the load-bearing walls.
