"""Separate historical customer inbox copies from classification ignored.

Only unassigned, uncredited ignored rows are eligible. The audit table makes
the exact status changes reversible without touching reply credit or recipients.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"


def upgrade():
    bind = op.get_bind()
    op.add_column("emails", sa.Column("manually_ignored", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_table("email_status_0017_rollback",
        sa.Column("email_id", sa.Integer, primary_key=True),
        sa.Column("old_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False))
    rows = bind.execute(sa.text("""SELECT e.id, e.internet_message_id, e.receiver, e.mailbox_id, m.address
        FROM emails e JOIN mailboxes m ON m.id=e.mailbox_id
        WHERE e.folder='inbox' AND e.classification='CUSTOMER'
        ORDER BY e.received_time, e.id""")).mappings().all()
    groups = {}
    for row in rows:
        key = (row["internet_message_id"] or "").strip().casefold()
        key = ("message", key) if key else ("local", row["id"])
        groups.setdefault(key, []).append(row)
    candidates = {row[0] for row in bind.execute(sa.text("""SELECT id FROM emails
        WHERE status='IGNORED' AND folder='inbox' AND classification='CUSTOMER'
        AND assigned_employee_id IS NULL AND replied_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM email_recipients r WHERE r.email_id=emails.id)"""))}
    for copies in groups.values():
        direct = [row for row in copies if row["address"].strip().casefold() in
                  {address.strip().casefold() for address in row["receiver"].replace(";", ",").split(",")}]
        primary = (direct or copies)[0]
        for row in copies:
            if row["id"] not in candidates:
                continue
            status = "DUPLICATE_COPY" if row is not primary and row in direct else "OBSERVER_COPY"
            bind.execute(sa.text("INSERT INTO email_status_0017_rollback (email_id,old_status,new_status) VALUES (:id,'IGNORED',:status)"), {"id": row["id"], "status": status})
            bind.execute(sa.text("UPDATE emails SET status=:status WHERE id=:id"), {"id": row["id"], "status": status})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""UPDATE emails SET status=(SELECT old_status FROM email_status_0017_rollback
        WHERE email_id=emails.id) WHERE id IN (SELECT email_id FROM email_status_0017_rollback)
        AND status=(SELECT new_status FROM email_status_0017_rollback WHERE email_id=emails.id)"""))
    op.drop_table("email_status_0017_rollback")
    op.drop_column("emails", "manually_ignored", mssql_drop_default=True)
