"""
Central configuration module.
All environment variables are loaded here and exposed as constants.
Import from this module rather than calling os.getenv() directly.
"""

import os
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")
NASDAQ_DATA_LINK_KEY: str = os.getenv("NASDAQ_DATA_LINK_KEY", "")
DB_PATH: str = os.getenv("DB_PATH", "data/processed/main.db")
POSTGRES_URL: str = os.getenv("POSTGRES_URL", "")

# Keys that must be present (non-empty) before Phase 1 data fetching
_REQUIRED_KEYS: dict[str, str] = {
    "FRED_API_KEY": FRED_API_KEY,
}


def validate(required_keys: dict[str, str] | None = None) -> None:
    """
    Raise ValueError if any required key is missing.
    By default checks FRED_API_KEY (needed for Phase 1).
    Pass a custom dict to override.
    """
    keys = required_keys if required_keys is not None else _REQUIRED_KEYS
    missing = [name for name, value in keys.items() if not value]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}\n"
            "Set them in your .env file at the repo root.\n"
            "Example: FRED_API_KEY=your_key_here"
        )
