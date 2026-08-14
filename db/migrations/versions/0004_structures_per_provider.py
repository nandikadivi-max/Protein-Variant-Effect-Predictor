"""Let a protein keep a predicted model and an experimental structure at once.

sequence_hash alone was the primary key of `structures`, so a protein could
hold exactly one. That is what made resolving a PDB id overwrite the AlphaFold
model *globally* — one visitor searching 1TUP changed what everyone saw for
TP53 — and the "experimental beats predicted" rule existed only to decide who
won that collision.

Widening the key to (sequence_hash, provider) lets both coexist and moves the
choice to request time: a gene-name search gets the full-length prediction, a
PDB search gets the experimental entry, and neither disturbs the other.

Deliberately NOT a surrogate key with (sequence_hash, provider, pdb_id)
uniqueness. That would also allow several PDB entries per protein, but needs a
new identity column and a backfill, and the first draft of it was wrong:
`add_column` with autoincrement does not create a sequence in Postgres, so the
backfill would have failed *after* dropping the primary key. The composite key
covers the actual requirement — predicted versus experimental — in three
statements with nothing to backfill. A second PDB entry for the same protein
simply replaces the first, which is an acceptable trade for the reduced risk.

No existing row can violate the new key: with sequence_hash as the primary
key, two rows for one protein were impossible.

Revision ID: 0004_structures_per_provider
Revises: 0003_structure_pdb_lazy
"""

from alembic import op

revision = "0004_structures_per_provider"
down_revision = "0003_structure_pdb_lazy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("structures_pkey", "structures", type_="primary")
    op.create_primary_key(
        "structures_pkey", "structures", ["sequence_hash", "provider"]
    )


def downgrade() -> None:
    # Collapsing back to one structure per protein has to discard the extras.
    # Predictions are cheap to re-fetch, so an experimental entry is kept in
    # preference to an AlphaFold model where a protein has both.
    op.execute(
        """
        DELETE FROM structures s
        USING structures other
        WHERE s.sequence_hash = other.sequence_hash
          AND s.provider = 'alphafold'
          AND other.provider <> 'alphafold'
        """
    )
    op.drop_constraint("structures_pkey", "structures", type_="primary")
    op.create_primary_key("structures_pkey", "structures", ["sequence_hash"])
