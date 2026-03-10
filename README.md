# Trading Infrastructure

A systematic trading research and execution infrastructure.

## Directory Structure

```
trading-infrastructure/
├── data/
│   ├── raw/         # Raw data fetched from external sources (not committed — always re-fetchable)
│   ├── processed/   # Cleaned, transformed data and DuckDB database files
│   └── cache/       # Temporary cached API responses (not committed)
├── research/
│   ├── signals/     # Signal generation notebooks and scripts
│   ├── strategies/  # Strategy definitions, backtests, and parameter files
│   └── archive/     # Retired or superseded research
├── systems/
│   ├── data_feeds/  # Data ingestion modules (FRED, Polygon, etc.)
│   ├── risk/        # Position sizing, drawdown limits, exposure management
│   ├── execution/   # Order routing and trade execution logic
│   └── utils/       # Shared utilities (DB connection, helpers)
├── reports/         # Generated reports, charts, and summaries
├── docs/            # Project documentation and runbooks
└── scripts/         # One-off scripts, verification, and maintenance tasks
```

## Setup

```bash
bash setup.sh
```

## Verification

```bash
python scripts/verify_phase0.py
```
