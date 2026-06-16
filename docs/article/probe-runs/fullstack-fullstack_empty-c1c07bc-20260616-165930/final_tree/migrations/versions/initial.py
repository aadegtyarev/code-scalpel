"""Create keys table

Revision ID: 0001
Revises:
Create Date: 2026-05-11 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False, comment="SHA-256 hex digest of the API key"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_keys_key_hash"), "keys", ["key_hash"], unique=False)
    op.create_index(op.f("ix_keys_is_active"), "keys", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_keys_is_active"), table_name="keys")
    op.drop_index(op.f("ix_keys_key_hash"), table_name="keys")
    op.drop_table("keys")
