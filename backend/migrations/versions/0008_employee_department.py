"""Add department grouping for employees."""
from alembic import op
import sqlalchemy as sa

revision="0008"
down_revision="0007"

def upgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("employees")}
    if "department" not in columns:
        op.add_column("employees",sa.Column("department",sa.String(120),nullable=False,server_default="General"))

def downgrade():
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("employees")}
    if "department" in columns:op.drop_column("employees","department")
