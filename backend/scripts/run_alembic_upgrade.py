"""Controlled Alembic upgrade for Compose migrate services.

Set AUTO_MIGRATE=false to skip (deploy freeze / rollback without schema change).
Default: run ``alembic upgrade head``.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _truthy(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def main() -> int:
    if _truthy(os.environ.get("AUTO_MIGRATE")):
        print("AUTO_MIGRATE=true — running: alembic upgrade head", flush=True)
        return subprocess.call(["alembic", "upgrade", "head"])
    print("AUTO_MIGRATE=false — skipping alembic upgrade", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
