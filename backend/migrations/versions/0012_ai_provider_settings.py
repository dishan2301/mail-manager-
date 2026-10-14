"""Persist selected AI provider and encrypted provider keys."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"

def upgrade():
    op.create_table("ai_provider_settings",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("provider",sa.String(20),nullable=False),
        sa.Column("model",sa.String(120),nullable=False),
        sa.Column("keys",sa.JSON(),nullable=False))

def downgrade():
    op.drop_table("ai_provider_settings")
