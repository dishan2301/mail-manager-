"""Keep separate coaching findings for employees sharing a conversation."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"


def upgrade():
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("conversation_ai_reviews")
    old = next((item for item in constraints if item["column_names"] == ["mailbox_id", "conversation_key"]), None)
    if old is None and any(item["column_names"] == ["mailbox_id", "conversation_key", "employee_id"] for item in constraints):return
    if old is None:raise RuntimeError("Expected conversation review uniqueness constraint is missing")
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
    with op.batch_alter_table("conversation_ai_reviews", naming_convention=convention) as batch:
        batch.drop_constraint(old["name"] or "uq_conversation_ai_reviews_mailbox_id_conversation_key", type_="unique")
        batch.create_unique_constraint("uq_review_mailbox_conversation_employee", ["mailbox_id", "conversation_key", "employee_id"])


def downgrade():
    # Retain the most recently analyzed employee if a thread has multiple reviews.
    table = sa.table("conversation_ai_reviews", sa.column("id"), sa.column("mailbox_id"), sa.column("conversation_key"), sa.column("analyzed_at"))
    rows = op.get_bind().execute(sa.select(table).order_by(table.c.analyzed_at.desc(), table.c.id.desc()))
    seen = set()
    duplicates = []
    for row in rows:
        key = (row.mailbox_id, row.conversation_key)
        if key in seen: duplicates.append(row.id)
        seen.add(key)
    if duplicates: op.get_bind().execute(table.delete().where(table.c.id.in_(duplicates)))
    with op.batch_alter_table("conversation_ai_reviews") as batch:
        batch.drop_constraint("uq_review_mailbox_conversation_employee", type_="unique")
        batch.create_unique_constraint("uq_review_mailbox_conversation", ["mailbox_id", "conversation_key"])
