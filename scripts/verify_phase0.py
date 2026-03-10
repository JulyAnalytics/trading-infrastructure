"""
Phase 0 verification script.
Run from the repo root: python scripts/verify_phase0.py
All checks must pass before proceeding to Phase 1.
"""

import sys

REQUIRED_PACKAGES = [
    "yfinance", "pandas", "numpy", "scipy", "statsmodels",
    "sklearn", "matplotlib", "plotly", "duckdb", "psycopg2",
    "dotenv", "requests", "fredapi", "pandas_datareader",
]

REQUIRED_TABLES = {"macro_series", "options_chains", "vol_signals", "trade_log"}

REQUIRED_ENV_KEYS = ["FRED_API_KEY", "POLYGON_API_KEY", "DB_PATH"]


def check(label: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def verify_python_version() -> bool:
    print("\n1. Python version")
    major, minor = sys.version_info[:2]
    return check(
        f"Python {major}.{minor}",
        major == 3 and minor >= 11,
        f"need 3.11+, got {major}.{minor}",
    )


def verify_packages() -> bool:
    print("\n2. Package imports")
    all_ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
            check(pkg, True)
        except ImportError as e:
            check(pkg, False, str(e))
            all_ok = False
    return all_ok


def verify_database() -> bool:
    print("\n3. DuckDB connection and tables")
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        import duckdb

        db_path = os.getenv("DB_PATH", "data/processed/main.db")
        if not os.path.exists(db_path):
            check("Database file exists", False, f"{db_path} not found — run: python systems/db_init.py")
            return False

        con = duckdb.connect(db_path)
        existing = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        con.close()

        check("DuckDB connection", True)
        all_ok = True
        for table in sorted(REQUIRED_TABLES):
            ok = table in existing
            check(f"Table: {table}", ok, "" if ok else "missing — run: python systems/db_init.py")
            all_ok = all_ok and ok
        return all_ok
    except Exception as e:
        check("DuckDB connection", False, str(e))
        return False


def verify_env() -> bool:
    print("\n4. .env file and required keys")
    import os
    from dotenv import load_dotenv

    if not os.path.exists(".env"):
        check(".env file exists", False, "create a .env file in the repo root")
        return False

    check(".env file exists", True)
    load_dotenv()

    all_ok = True
    for key in REQUIRED_ENV_KEYS:
        value = os.getenv(key, "")
        present = bool(value)
        detail = "set" if present else "empty (set in .env before Phase 1)"
        check(f"{key}", present, detail)
        # Not setting all_ok=False for empty keys — empty is acceptable at Phase 0
    return all_ok


def main() -> None:
    print("=" * 50)
    print("Phase 0 Verification")
    print("=" * 50)

    results = [
        verify_python_version(),
        verify_packages(),
        verify_database(),
        verify_env(),
    ]

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 50)
    print(f"Summary: {passed}/{total} checks passed")
    if passed == total:
        print("All checks passed. Ready for Phase 1.")
    else:
        print("Fix the failing checks above before proceeding.")
    print("=" * 50)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
