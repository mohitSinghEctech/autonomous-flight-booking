"""add payments.payment_session_id

The model gained this column without a migration, so the database never had it
and every payment query failed. Found by the integration tests.

Revision ID: c7d3e1f0a2b5
Revises: b41c2e7d9a10
Create Date: 2026-10-06 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d3e1f0a2b5'
down_revision: Union[str, Sequence[str], None] = 'b41c2e7d9a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payments', sa.Column('payment_session_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payments', 'payment_session_id')
