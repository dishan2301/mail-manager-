"""Track when an email was opened in the OEIS dashboard."""
from alembic import op
import sqlalchemy as sa

revision="0007"
down_revision="0006"

def upgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("emails")}
    if "read_at" not in columns: op.add_column("emails",sa.Column("read_at",sa.DateTime(timezone=True),nullable=True))

def downgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("emails")}
    if "read_at" in columns: op.drop_column("emails","read_at")
