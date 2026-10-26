from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import routes
from app.core.database import Base
from app.models.entities import Mailbox


def test_readiness_returns_count_instead_of_settings(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(routes, "report_mailbox_available", lambda: False)
    with Session(engine) as db:
        db.add(Mailbox(address="ready@example.com", display_name="Ready"))
        db.commit()
        result = routes.system_readiness(principal={"role": "admin"}, db=db)
    assert result["configured_mailboxes"] == 1
    assert all("secret" not in str(value).lower() for value in result.values())


def test_one_fresh_mailbox_does_not_hide_another_stale_mailbox(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(routes, "report_mailbox_available", lambda: False)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([
            Mailbox(address="fresh@example.com", display_name="Fresh", last_synced_at=now),
            Mailbox(address="stale@example.com", display_name="Stale", last_synced_at=now-timedelta(hours=2)),
        ])
        db.commit()
        result = routes.system_readiness(principal={"role": "admin"}, db=db)
    assert result["stale_mailboxes"] == 1
    assert [row["address"] for row in result["mailbox_health"] if row["stale"]] == ["stale@example.com"]
    assert result["operational"] is False
