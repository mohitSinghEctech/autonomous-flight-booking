"""add passenger travel details and provider booking id

Revision ID: a7c31f9d2b84
Revises: e5a9538f0ce3
Create Date: 2026-10-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c31f9d2b84'
down_revision: Union[str, Sequence[str], None] = 'e5a9538f0ce3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('passengers', sa.Column('title', sa.String(length=10), nullable=True))
    op.add_column('passengers', sa.Column('gender', sa.String(length=10), nullable=True))
    op.add_column('passengers', sa.Column('born_on', sa.Date(), nullable=True))
    op.add_column('passengers', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('passengers', sa.Column('phone_number', sa.String(length=30), nullable=True))
    op.add_column('bookings', sa.Column('provider_booking_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('bookings', 'provider_booking_id')
    op.drop_column('passengers', 'phone_number')
    op.drop_column('passengers', 'email')
    op.drop_column('passengers', 'born_on')
    op.drop_column('passengers', 'gender')
    op.drop_column('passengers', 'title')
