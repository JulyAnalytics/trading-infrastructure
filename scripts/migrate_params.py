"""
Seed / inspect the parameter registry (v1.0 Phase 0).

Idempotent: components that already have an active version are left alone;
missing ones are seeded from code defaults (systems/params/models.py), which
mirror the v0.5 config.py values exactly.

Usage:
    python scripts/migrate_params.py            # seed missing + report
    python scripts/migrate_params.py --check    # also verify every legacy
                                                # config name resolves
    python scripts/migrate_params.py --reseed marcus
                                                # force a new defaults version
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from systems.params import (  # noqa: E402
    COMPONENTS, MODEL_BY_COMPONENT, LEGACY_CONFIG_MAP,
    get_active, set_params,
)


def seed_and_report() -> None:
    print(f"{'component':<10} {'version':>7} {'hash':<14} fields")
    print("─" * 46)
    for component in COMPONENTS:
        active = get_active(component)   # seeds defaults if absent
        n_fields = len(active.model.to_dict())
        print(f"{component:<10} {active.version:>7} {active.hash:<14} {n_fields}")


def check_legacy_names() -> int:
    import config
    failures = 0
    for name in sorted(LEGACY_CONFIG_MAP):
        try:
            value = getattr(config, name)
            summary = repr(value)
            if len(summary) > 60:
                summary = summary[:57] + "…"
            print(f"  ✓ config.{name} = {summary}")
        except Exception as e:
            failures += 1
            print(f"  ✗ config.{name} FAILED: {e}")
    return failures


def reseed(component: str) -> None:
    cls = MODEL_BY_COMPONENT[component]
    active = set_params(component, cls().to_dict(),
                        note="reseed: code defaults via migrate_params.py")
    print(f"{component}: reseeded as v{active.version} ({active.hash})")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--reseed"] and len(args) == 2:
        reseed(args[1])
        sys.exit(0)

    seed_and_report()

    if "--check" in args:
        print("\nLegacy config-name resolution:")
        n_fail = check_legacy_names()
        if n_fail:
            print(f"\n{n_fail} legacy name(s) FAILED to resolve")
            sys.exit(1)
        print("\nAll legacy config names resolve through the registry.")
