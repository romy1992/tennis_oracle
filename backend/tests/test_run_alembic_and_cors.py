"""Unit tests for AUTO_MIGRATE helper and empty CORS regex handling."""

from __future__ import annotations

from backend.scripts.run_alembic_upgrade import _truthy


def test_auto_migrate_truthy_defaults():
    assert _truthy(None) is True
    assert _truthy("true") is True
    assert _truthy("1") is True
    assert _truthy("false") is False
    assert _truthy("0") is False
    assert _truthy("off") is False
    assert _truthy("") is False
