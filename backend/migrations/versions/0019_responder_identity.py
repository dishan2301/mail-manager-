"""Keep the credited responder separate from current assignment."""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"


def upgrade():
    with op.batch_alter_table("emails") as batch:
        batch.add_column(sa.Column("responder_employee_id", sa.Integer,
                                   sa.ForeignKey("employees.id", name="fk_emails_responder_employee_id"), nullable=True))
        batch.add_column(sa.Column("assignment_overridden", sa.Boolean,
                                   nullable=False, server_default=sa.false()))
    op.execute(sa.text("""UPDATE emails SET responder_employee_id=assigned_employee_id
        WHERE status='REPLIED' AND assigned_employee_id IS NOT NULL"""))


def downgrade():
    with op.batch_alter_table("emails") as batch:
        batch.drop_column("assignment_overridden", mssql_drop_default=True)
        batch.drop_column("responder_employee_id")
