"""Store daily AI coaching observations and explicit enablement consent."""
from alembic import op
import sqlalchemy as sa

revision="0009"
down_revision="0008"

def upgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    if "ai_review_settings" not in tables:
        _create_settings()
    if "conversation_ai_reviews" in tables:return
    _create_reviews()

def _create_settings():
    op.create_table(
        "ai_review_settings",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("approved_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
        sa.Column("approved_at",sa.DateTime(timezone=True),nullable=True),
    )

def _create_reviews():
    op.create_table(
        "conversation_ai_reviews",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("mailbox_id",sa.Integer(),sa.ForeignKey("mailboxes.id"),nullable=False),
        sa.Column("conversation_key",sa.String(512),nullable=False),
        sa.Column("employee_id",sa.Integer(),sa.ForeignKey("employees.id"),nullable=False),
        sa.Column("received_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("last_message_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="pending"),
        sa.Column("analysis",sa.Text(),nullable=True),
        sa.Column("error_code",sa.String(80),nullable=True),
        sa.Column("analyzed_at",sa.DateTime(timezone=True),nullable=True),
        sa.UniqueConstraint("mailbox_id","conversation_key"),
    )
    op.create_index("ix_conversation_ai_reviews_mailbox_id","conversation_ai_reviews",["mailbox_id"])
    op.create_index("ix_conversation_ai_reviews_employee_id","conversation_ai_reviews",["employee_id"])
    op.create_index("ix_conversation_ai_reviews_received_at","conversation_ai_reviews",["received_at"])

def downgrade():
    op.drop_index("ix_conversation_ai_reviews_received_at",table_name="conversation_ai_reviews")
    op.drop_index("ix_conversation_ai_reviews_employee_id",table_name="conversation_ai_reviews")
    op.drop_index("ix_conversation_ai_reviews_mailbox_id",table_name="conversation_ai_reviews")
    op.drop_table("conversation_ai_reviews")
    op.drop_table("ai_review_settings")
