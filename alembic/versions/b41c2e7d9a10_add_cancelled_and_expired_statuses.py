"""add cancelled/expired booking statuses and expired payment status

Revision ID: b41c2e7d9a10
Revises: 2dfcdf02fd3c
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b41c2e7d9a10'
down_revision: Union[str, Sequence[str], None] = '2dfcdf02fd3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLAlchemy stores enum NAMES, so the new values are the upper-case names.
    op.execute("ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")
    op.execute("ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'EXPIRED'")
    op.execute("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'EXPIRED'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL cannot drop a value from an enum type; leaving them is harmless.
    pass
