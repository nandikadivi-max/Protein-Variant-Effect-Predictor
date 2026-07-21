"""structures: nullable structure_uri + pdb_id for lazy RCSB fetch

Revision ID: 0003_structure_pdb_lazy
Revises: 0002_structure_source_url
Create Date: 2026-07-20

A PDB-sourced protein records its structure intent at resolve time
(provider=rcsb, pdb_id, sifts_map_uri) but the actual RCSB file is fetched
lazily on first view. That means structure_uri must be nullable, and we add
pdb_id so the lazy fetch knows which entry to download.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_structure_pdb_lazy"
down_revision: Union[str, None] = "0002_structure_source_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("structures", "structure_uri", nullable=True)
    op.add_column("structures", sa.Column("pdb_id", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("structures", "pdb_id")
    op.alter_column("structures", "structure_uri", nullable=False)
