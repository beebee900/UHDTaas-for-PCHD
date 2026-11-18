"""Register every WP14a model in the configured model registry with its validation.

Run `python -m ahdt.models.register`. The registry is the JSON file in profile p0 and
MLflow in the container profiles (`ATRA_BACKEND__MODEL_REGISTRY`).
"""

from __future__ import annotations

import asyncio

from ahdt.models.catalogue import build_catalogue, register_all
from ahdt.models.validation import run_checks
from atra.backends import Backends
from atra.config import get_settings


async def register() -> int:
    catalogue = build_catalogue()
    checks = run_checks(catalogue)
    failed = [m for m, check in checks.items() if not check.passed]
    if failed:
        raise SystemExit(f"validation failed for: {', '.join(failed)}")
    backends = Backends(get_settings(), "ahdt")
    try:
        entries = await register_all(
            backends.models, catalogue,
            validations={m: ch.validation() for m, ch in checks.items()},
            metrics={m: {ch.metric: ch.value} for m, ch in checks.items()})
    finally:
        await backends.close()
    return len(entries)


def main() -> None:
    print(f"registered {asyncio.run(register())} models")


if __name__ == "__main__":
    main()
