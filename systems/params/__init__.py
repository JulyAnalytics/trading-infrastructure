"""
Parameter registry — versioned, GUI-editable source of truth for every
tunable in the system.

    from systems.params import get_params
    p = get_params("sarah")          # typed SarahParams, active version
    p.vol_tickers                     # -> ["SPY", "QQQ", ...]

    from systems.params import set_params
    set_params("marcus", {"divergence_threshold_vc": 0.55},
               note="calibrated against 2018-2025 backfill")

Every run should stamp the hashes it executed under:

    from systems.params import all_active_hashes
    run_record["param_hashes"] = all_active_hashes()

Legacy `from config import CONSTANT` keeps working — config.py resolves those
names through this package (see compat.LEGACY_CONFIG_MAP).
"""
from .models import (
    COMPONENTS,
    MODEL_BY_COMPONENT,
    DataParams,
    JordanParams,
    MarcusParams,
    OpsParams,
    ParamsBase,
    PriyaParams,
    SarahParams,
)
from .store import (
    ActiveParams,
    activate_version,
    active_hash,
    all_active_hashes,
    get_active,
    get_history,
    get_params,
    invalidate_cache,
    payload_hash,
    set_params,
)
from .compat import LEGACY_CONFIG_MAP, REGISTRY_BACKED_NAMES, config_value

__all__ = [
    "COMPONENTS", "MODEL_BY_COMPONENT", "ParamsBase",
    "MarcusParams", "SarahParams", "PriyaParams",
    "JordanParams", "OpsParams", "DataParams",
    "ActiveParams", "get_params", "get_active", "set_params",
    "get_history", "activate_version", "active_hash",
    "all_active_hashes", "payload_hash", "invalidate_cache",
    "LEGACY_CONFIG_MAP", "REGISTRY_BACKED_NAMES", "config_value",
]
