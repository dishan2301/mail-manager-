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
