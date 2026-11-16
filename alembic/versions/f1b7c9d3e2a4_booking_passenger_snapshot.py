"""booking passengers keep their own copy of the traveller; saved passengers can be deleted

Revision ID: f1b7c9d3e2a4
Revises: 4479a967ab31
Create Date: 2026-11-12

Until now a booking only pointed at the saved passenger, so editing a saved
passenger rewrote past bookings and deleting one violated the foreign key.

  - booking_passengers gets the traveller's details as booked (snapshot)
  - existing rows are backfilled from passengers. That is exact: saved
    passengers could not be edited before this revision.
  - passenger_id becomes nullable, ON DELETE SET NULL
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1b7c9d3e2a4"
down_revision: Union[str, Sequence[str], None] = "4479a967ab31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Unnamed in e5a9538f0ce3, so Postgres named it.
FK_NAME = "booking_passengers_passenger_id_fkey"

SNAPSHOT_COLUMNS = ["title", "given_name", "family_name", "gender", "born_on", "email", "phone_number"]


def upgrade() -> None:
    op.add_column("booking_passengers", sa.Column("title", sa.String(length=10), nullable=True))
    op.add_column("booking_passengers", sa.Column("given_name", sa.String(length=100), nullable=True))
    op.add_column("booking_passengers", sa.Column("family_name", sa.String(length=100), nullable=True))
    op.add_column("booking_passengers", sa.Column("gender", sa.String(length=10), nullable=True))
    op.add_column("booking_passengers", sa.Column("born_on", sa.Date(), nullable=True))
    op.add_column("booking_passengers", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("booking_passengers", sa.Column("phone_number", sa.String(length=30), nullable=True))

    assignments = ", ".join(f"{column} = p.{column}" for column in SNAPSHOT_COLUMNS)
    op.execute(
        f"UPDATE booking_passengers AS bp SET {assignments} "
        "FROM passengers AS p WHERE p.id = bp.passenger_id"
    )

    op.alter_column("booking_passengers", "given_name", nullable=False)
    op.alter_column("booking_passengers", "family_name", nullable=False)

    op.drop_constraint(FK_NAME, "booking_passengers", type_="foreignkey")
    op.alter_column("booking_passengers", "passenger_id", nullable=True)
    op.create_foreign_key(
        FK_NAME, "booking_passengers", "passengers",
        ["passenger_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    # Rows whose saved passenger was deleted only exist as a snapshot. The old
    # schema can't hold them; refuse instead of silently dropping booking history.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM booking_passengers WHERE passenger_id IS NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade: some booked travellers no longer have a saved passenger '
                                '(booking_passengers.passenger_id IS NULL).';
            END IF;
        END $$;
        """
    )

    op.drop_constraint(FK_NAME, "booking_passengers", type_="foreignkey")
    op.alter_column("booking_passengers", "passenger_id", nullable=False)
    op.create_foreign_key(FK_NAME, "booking_passengers", "passengers", ["passenger_id"], ["id"])

    for column in reversed(SNAPSHOT_COLUMNS):
        op.drop_column("booking_passengers", column)
