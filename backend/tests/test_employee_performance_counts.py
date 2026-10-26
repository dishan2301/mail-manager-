from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Classification, Email, EmailStatus, Employee, Mailbox, SLATier
from app.repositories.email import EmailRepository


def test_replied_email_is_not_current_critical_work():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        employee = Employee(name="Owner", email="owner@indianinfotech.org", active=True)
        mailbox = Mailbox(address="owner@indianinfotech.org", display_name="Owner")
        db.add_all([employee, mailbox])
        db.flush()
        db.add(Email(mailbox_id=mailbox.id, message_id="one", sender="customer@example.com", receiver=mailbox.address,
                     subject="Answered", received_time=datetime.now(timezone.utc), folder="inbox",
                     classification=Classification.CUSTOMER, status=EmailStatus.REPLIED,
                     sla_tier=SLATier.CRITICAL, assigned_employee_id=employee.id, responder_employee_id=employee.id))
        db.commit()
        row = EmailRepository(db).employee_performance()[0]
    assert row["replied"] == 1
    assert row["pending"] == row["critical"] == 0
