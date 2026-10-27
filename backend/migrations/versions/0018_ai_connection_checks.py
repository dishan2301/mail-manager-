"""Retain the latest synthetic AI connection check."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"


def upgrade():
    op.create_table("ai_connection_checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("ai_connection_checks")
