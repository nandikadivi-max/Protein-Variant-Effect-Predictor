"""add structures.source_url

Revision ID: 0002_structure_source_url
Revises: 0001_initial
Create Date: 2026-07-20

Records the upstream provenance URL (AlphaFold DB / RCSB) a structure file
was fetched from, so it survives across cache reads and can be shown in the
UI. Nullable because rows written before this column existed have no value.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_structure_source_url"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("structures", sa.Column("source_url", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("structures", "source_url")
