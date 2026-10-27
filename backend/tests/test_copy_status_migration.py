import importlib
from datetime import datetime, timezone

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Classification, Email, EmailStatus, Mailbox


def test_copy_status_migration_changes_only_eligible_rows_and_rolls_back():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    with sessionmaker(bind=engine)() as db:
        boxes = [Mailbox(address="a@indianinfotech.org", display_name="A"),
                 Mailbox(address="b@indianinfotech.org", display_name="B"),
                 Mailbox(address="ceo@indianinfotech.org", display_name="CEO")]
        db.add_all(boxes); db.flush()
        def email(box, name, internet_id, receiver, status, classification=Classification.CUSTOMER):
            return Email(mailbox_id=box.id, message_id=name, internet_message_id=internet_id,
                         sender="customer@example.com", receiver=receiver, subject="Request",
                         received_time=now, folder="inbox", classification=classification, status=status)
        rows = [email(boxes[0], "primary", "<same>", "a@indianinfotech.org, b@indianinfotech.org", EmailStatus.PENDING),
                email(boxes[1], "duplicate", "<same>", "a@indianinfotech.org, b@indianinfotech.org", EmailStatus.IGNORED),
                email(boxes[2], "observer", "<same>", "a@indianinfotech.org, b@indianinfotech.org", EmailStatus.IGNORED),
                email(boxes[2], "ignored", "<other>", "a@indianinfotech.org", EmailStatus.IGNORED, Classification.IGNORE)]
        db.add_all(rows); db.commit()
        ids = [row.id for row in rows]
    migration = importlib.import_module("migrations.versions.0017_copy_statuses")
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE emails DROP COLUMN manually_ignored")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            statuses = dict(connection.execute(text("SELECT id,status FROM emails")).all())
            assert [statuses[id] for id in ids] == ["PENDING", "DUPLICATE_COPY", "OBSERVER_COPY", "IGNORED"]
            assert connection.execute(text("SELECT count(*) FROM email_status_0017_rollback")).scalar_one() == 2
            migration.downgrade()
            statuses = dict(connection.execute(text("SELECT id,status FROM emails")).all())
            assert [statuses[id] for id in ids] == ["PENDING", "IGNORED", "IGNORED", "IGNORED"]
    engine.dispose()
