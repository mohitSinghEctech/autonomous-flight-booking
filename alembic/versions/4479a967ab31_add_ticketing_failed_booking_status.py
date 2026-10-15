"""add ticketing_failed booking status

Revision ID: 4479a967ab31
Revises: d8e2f4a6b1c3
Create Date: 2026-10-14 23:30:05.696970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4479a967ab31'
down_revision: Union[str, Sequence[str], None] = 'd8e2f4a6b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLAlchemy stores enum NAMES, so the label is the upper-case name.
    op.execute("ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'TICKETING_FAILED'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL cannot drop a value from an enum type; leaving it is harmless.
    pass
