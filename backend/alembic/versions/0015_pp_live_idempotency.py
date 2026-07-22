"""published_prediction live identity idempotency (content_version=1)

Revision ID: 0015_pp_live_idempotency
Revises: 0014_prematch_odds_snapshot
Create Date: 2026-07-22

Partial unique index prevents duplicate initial publications for the same
logical tip identity (event × selection × model × version × source) when the
global update pipeline is re-run. Corrections still append content_version > 1.
content_hash is NOT used for dedup (it embeds a random publication_id).

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0015_pp_live_idempotency"
down_revision: Union[str, None] = "0014_prematch_odds_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_published_prediction_live_identity_v1"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "published_prediction" not in tables:
        return

    existing = {idx["name"] for idx in inspector.get_indexes("published_prediction")}
    if INDEX_NAME in existing:
        return

    op.create_index(
        INDEX_NAME,
        "published_prediction",
        [
            "event_key",
            "selection",
            "model_version",
            "model_name",
            "publication_source",
        ],
        unique=True,
        postgresql_where=sa.text("content_version = 1"),
        sqlite_where=sa.text("content_version = 1"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "published_prediction" not in tables:
        return
    existing = {idx["name"] for idx in inspector.get_indexes("published_prediction")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="published_prediction")
