"""Save evidence-based coaching rubric separately from narrative review."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"

def upgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("conversation_ai_reviews")}
    if "rubric" not in columns:
        op.add_column("conversation_ai_reviews",sa.Column("rubric",sa.JSON(),nullable=True))

def downgrade():
    op.drop_column("conversation_ai_reviews","rubric")
