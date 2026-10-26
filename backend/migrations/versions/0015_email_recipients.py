"""Retain every To employee independently of the employee earning reply credit."""
from alembic import op
import sqlalchemy as sa

revision="0015"
down_revision="0014"


def upgrade():
    if "email_recipients" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("email_recipients",
            sa.Column("email_id",sa.Integer(),sa.ForeignKey("emails.id",ondelete="CASCADE"),primary_key=True),
            sa.Column("employee_id",sa.Integer(),sa.ForeignKey("employees.id",ondelete="CASCADE"),primary_key=True))
        op.create_index("ix_email_recipients_employee_id","email_recipients",["employee_id"])


def downgrade():
    op.drop_table("email_recipients")
