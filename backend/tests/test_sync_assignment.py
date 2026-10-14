import asyncio
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Email, Employee, Mailbox
from app.services import sync


def test_assignment_prefers_mailbox_then_recipient_and_never_random_employee():
    employees=[Employee(id=1,email="other@example.com",active=True),Employee(id=2,email="chaudharydishan90@outlook.com",active=True)]
    assert sync._assignee("other@example.com"," CHAUDHARYDISHAN90@OUTLOOK.COM ",employees)==2
    assert sync._assignee("external@example.com; OTHER@example.com","shared@example.com",employees)==1
    assert sync._assignee("external@example.com","unknown@example.com",employees) is None
    employees[1].active=False
    assert sync._assignee("chaudharydishan90@outlook.com","chaudharydishan90@outlook.com",employees) is None
    assert sync._assignee("","unknown@example.com",[]) is None


def test_sync_assigns_inbox_mail_and_preserves_explicit_assignments(monkeypatch):
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    address="chaudharydishan90@outlook.com"
    with sessions() as db:
        db.add_all([Mailbox(address=address,display_name="Dishan",provider="gmail"),Employee(name="Dishan",email=address,active=True),Employee(name="Other",email="other@example.com",active=True)])
        db.commit()
        owner_id=db.scalar(select(Employee.id).where(Employee.email==address))
        other_id=db.scalar(select(Employee.id).where(Employee.email=="other@example.com"))
    class Adapter:
        def __init__(self,*args):pass
        async def sync_mailbox(self,*args):
            return [dict(id=folder,receivedDateTime="2026-10-14T00:00:00Z",subject="Hello",_folder=folder,toRecipients=[{"emailAddress":{"address":"other@example.com"}}],**{"from":{"emailAddress":{"address":"customer@example.com"}}}) for folder in ("inbox","sentitems")],"delta"
    monkeypatch.setattr(sync,"SessionLocal",sessions)
    monkeypatch.setattr(sync,"get_settings",lambda:SimpleNamespace())
    monkeypatch.setattr(sync,"get_mailbox_token",lambda *_:"token")
    monkeypatch.setattr(sync,"GmailDeltaSync",Adapter)
    asyncio.run(sync.sync_all_mailboxes())
    with sessions() as db:
        inbox=db.scalar(select(Email).where(Email.folder=="inbox"))
        assert inbox.assigned_employee_id==owner_id
        assert db.scalar(select(Email).where(Email.folder=="sentitems")).assigned_employee_id is None
        inbox.assigned_employee_id=None
        db.commit()
    asyncio.run(sync.sync_all_mailboxes())
    with sessions() as db:
        inbox=db.scalar(select(Email).where(Email.folder=="inbox"))
        assert inbox.assigned_employee_id==owner_id
        inbox.assigned_employee_id=other_id
        db.commit()
    asyncio.run(sync.sync_all_mailboxes())
    with sessions() as db:
        assert db.scalar(select(Email).where(Email.folder=="inbox")).assigned_employee_id==other_id
    engine.dispose()
