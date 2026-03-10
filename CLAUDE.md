# Claude Code Task: Integrate V1 Macro Files

## Context
I have a `trading-infrastructure` project folder open in VS Code. I also have a zip file at `~/Downloads/phase1_macro.zip` containing V1 macro dashboard files. I need you to integrate the zip contents into this project.

## What the zip contains (flat structure)
```
phase1_macro.zip
├── config.py
├── macro_feed.py
├── regime_classifier.py
├── macro_dashboard.py
├── db.py
├── scheduler.py
├── requirements.txt
└── README.md
```

## Target project structure (already exists)
```
trading-infrastructure/
├── data/
├── docs/
├── reports/
├── research/
├── scripts/
├── systems/          ← V1 files go here
├── venv/
├── README.md
├── requirements.txt
└── setup.sh
```

## Step 1: Unzip
Unzip `~/Downloads/phase1_macro.zip` into `/tmp/phase1_macro`.
Find the actual path of the trading-infrastructure project (it's the current working directory — use `pwd` to confirm).
Store that path as the project root for all subsequent steps.

## Step 2: Create subdirectory structure inside systems/
Create the following directories if they don't exist:
- `systems/data_feeds/`
- `systems/signals/`
- `systems/dashboard/`
- `systems/utils/`

Also create empty `__init__.py` files in each of those four directories and in `systems/` itself.

## Step 3: Copy files to correct locations
| Source (from zip) | Destination (in project) |
|-------------------|--------------------------|
| `config.py` | project root (`./config.py`) |
| `scheduler.py` | project root (`./scheduler.py`) |
| `macro_feed.py` | `systems/data_feeds/macro_feed.py` |
| `db.py` | `systems/utils/db.py` |
| `regime_classifier.py` | `systems/signals/regime_classifier.py` |
| `macro_dashboard.py` | `systems/dashboard/macro_dashboard.py` |

Do NOT copy `requirements.txt` from the zip yet — handle it in Step 5.

## Step 4: Fix import paths in the four systems/ files
Each of the four files copied into `systems/` subdirectories contains this line:
```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

In `macro_feed.py`, `db.py`, `regime_classifier.py`, and `macro_dashboard.py`, replace that line with:
```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
```

Also check each file for any imports that reference the old flat structure:
- `from config import` → should work unchanged (config.py is at project root, which is now on sys.path)
- `from utils.db import` → change to `from systems.utils.db import`
- `from signals.regime_classifier import` → change to `from systems.signals.regime_classifier import`

Apply all necessary import fixes.

## Step 5: Merge requirements.txt
Read both `requirements.txt` files (the existing project one and the one from the zip).
Produce a single merged `requirements.txt` at the project root with all unique entries, sorted alphabetically, with no duplicates.
Write it to `./requirements.txt`.

## Step 6: Create data directories
Create these directories if they don't exist:
- `data/raw/`
- `data/processed/`
- `data/cache/`
- `logs/`

## Step 7: Handle .env
Check if `.env` already exists at project root.
- If not: copy `.env.example` from the zip to `.env` at project root, then add a comment at the top: `# Fill in FRED_API_KEY — get free key at fred.stlouisfed.org/docs/api`
- If yes: leave it alone.

## Step 8: Smoke test
Run the following and report the output:
```bash
python systems/utils/db.py
```
Expected output: `Database ready.` with no errors.

If it fails, diagnose and fix the import or path issue, then re-run until it passes.

## Step 9: Report
Print a summary of:
- Every file created or modified
- The result of the smoke test
- Any issues encountered and how they were resolved
- The confirmed project root path

## Constraints
- Do not modify anything inside `venv/`
- Do not modify `setup.sh`
- Do not delete any existing files — only add or modify
- If any file already exists at the destination, overwrite it
