"""Persist matched reply evidence and audited manual links."""
from alembic import op
import sqlalchemy as sa

revision="0020"
down_revision="0019"


def upgrade():
    with op.batch_alter_table("emails") as batch:
        batch.add_column(sa.Column("reply_email_id",sa.Integer,sa.ForeignKey("emails.id",name="fk_emails_reply_email_id"),nullable=True))
        batch.add_column(sa.Column("reply_link_source",sa.String(20),nullable=True))


def downgrade():
    with op.batch_alter_table("emails") as batch:
        batch.drop_column("reply_link_source")
        batch.drop_column("reply_email_id")
