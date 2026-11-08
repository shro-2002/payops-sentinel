"""widen evidence_records.verification for cause-claim verdicts

Revision ID: a7c1e2d4f9b0
Revises: ddfe853968bd
Create Date: 2026-11-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7c1e2d4f9b0'
down_revision: Union[str, None] = 'ddfe853968bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("evidence_records", "verification", type_=sa.String(24), existing_type=sa.String(16),
                    existing_nullable=False)


def downgrade() -> None:
    op.alter_column("evidence_records", "verification", type_=sa.String(16), existing_type=sa.String(24),
                    existing_nullable=False)
