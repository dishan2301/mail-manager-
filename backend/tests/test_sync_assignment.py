import asyncio
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Email, Employee, Mailbox
from app.services import sync


def test_assignment_uses_to_recipient_not_monitoring_mailbox():
    employees=[Employee(id=1,email="other@indianinfotech.org",active=True),Employee(id=2,email="dishan@indianinfotech.org",active=True)]
    assert sync._assignee("other@indianinfotech.org"," DISHAN@INDIANINFOTECH.ORG ",employees)==1
    assert sync._assignee("external@example.com; OTHER@INDIANINFOTECH.ORG","shared@example.com",employees)==1
    assert sync._assignee("external@example.com","unknown@example.com",employees) is None
    employees[1].active=False
    assert sync._assignee("dishan@indianinfotech.org","dishan@indianinfotech.org",employees) is None
    assert sync._assignee("","unknown@example.com",[]) is None


def test_sync_assigns_to_recipient_and_reconciles_stale_assignments(monkeypatch):
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    address="dishan@indianinfotech.org"
    with sessions() as db:
        db.add_all([Mailbox(address=address,display_name="Dishan",provider="gmail"),Employee(name="Dishan",email=address,active=True),Employee(name="Other",email="other@indianinfotech.org",active=True)])
        db.commit()
        owner_id=db.scalar(select(Employee.id).where(Employee.email==address))
        other_id=db.scalar(select(Employee.id).where(Employee.email=="other@indianinfotech.org"))
    class Adapter:
        def __init__(self,*args):pass
        async def sync_mailbox(self,*args):
            return [dict(id=folder,receivedDateTime="2026-10-14T00:00:00Z",subject="Hello",_folder=folder,toRecipients=[{"emailAddress":{"address":address}}],**{"from":{"emailAddress":{"address":"sender@indianinfotech.org"}}}) for folder in ("inbox","sentitems")],"delta"
    monkeypatch.setattr(sync,"SessionLocal",sessions)
    monkeypatch.setattr(sync,"get_settings",lambda:SimpleNamespace())
    monkeypatch.setattr(sync,"get_mailbox_token",lambda *_:"token")
    monkeypatch.setattr(sync,"GmailDeltaSync",Adapter)
    asyncio.run(sync.sync_all_mailboxes())
    with sessions() as db:
        inbox=db.scalar(select(Email).where(Email.folder=="inbox"))
        assert inbox.assigned_employee_id==owner_id
        assert db.scalar(select(Employee).where(Employee.email=="sender@indianinfotech.org")) is None
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
        assert db.scalar(select(Email).where(Email.folder=="inbox")).assigned_employee_id==owner_id
    engine.dispose()


def test_cc_observers_do_not_owe_replies_and_actual_responder_gets_credit():
    from datetime import datetime, timedelta, timezone
    from app.models.entities import Classification, EmailStatus
    from app.repositories.email import EmailRepository
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    start=datetime(2026,10,26,10,tzinfo=timezone.utc)
    with sessions() as db:
        y=Employee(name="Y",email="y@indianinfotech.org",active=True)
        a=Employee(name="A",email="a@indianinfotech.org",active=True)
        ceo=Employee(name="CEO",email="ceo@indianinfotech.org",active=True)
        db.add_all([y,a,ceo]);db.flush()
        boxes=[Mailbox(address=person.email,display_name=person.name,provider="gmail") for person in (y,a,ceo)]
        db.add_all(boxes);db.flush()
        def message(box, ident, sender, timestamp, folder="inbox", target=None):
            return Email(mailbox_id=box.id,message_id=ident,internet_message_id="<original>" if ident=="original" else "<reply>",conversation_id="thread",subject="Help",sender=sender,receiver="y@indianinfotech.org",received_time=timestamp,sent_time=timestamp if folder=="sentitems" else None,folder=folder,in_reply_to=target,classification=Classification.CUSTOMER,status=EmailStatus.PENDING)
        copies=[message(box,"original","x@client.com",start) for box in boxes]
        db.add_all(copies);db.flush()
        sync.reconcile_replies(db,[y,a,ceo]);db.flush()
        assert copies[0].status==EmailStatus.PENDING
        assert copies[0].assigned_employee_id==y.id
        assert all(row.status==EmailStatus.IGNORED and row.assigned_employee_id is None for row in copies[1:])
        # A's reply can be observed in Y's inbox, even without access to A's Sent folder.
        reply=message(boxes[0],"reply",a.email,start+timedelta(hours=1),target="<original>")
        db.add(reply);db.flush()
        sync.reconcile_replies(db,[y,a,ceo]);db.flush()
        assert copies[0].status==EmailStatus.REPLIED
        assert copies[0].assigned_employee_id==a.id
        assert copies[0].replied_at==reply.received_time
        performance={row["id"]:row for row in EmailRepository(db).employee_performance()}
        assert performance[a.id]["replied"]==1
        assert performance[y.id]["pending"]==performance[y.id]["replied"]==0
        assert performance[ceo.id]["pending"]==performance[ceo.id]["replied"]==0
        # Reconciliation is safe on the next delta sync with no new messages.
        sync.reconcile_replies(db,[y,a,ceo]);db.flush()
        assert copies[0].assigned_employee_id==a.id
        assert EmailRepository(db).all_employee_reply_rate()["replied"]==1
    engine.dispose()


def test_ceo_monitoring_copy_assigns_to_employee_without_employee_mailbox():
    from datetime import datetime, timezone
    from app.models.entities import Classification, EmailStatus
    from app.repositories.email import EmailRepository
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        ceo=Employee(name="CEO",email="ceo@indianinfotech.org",active=True)
        a=Employee(name="A",email="a@indianinfotech.org",active=True)
        monitor=Mailbox(address=ceo.email,display_name="CEO monitor",provider="gmail")
        db.add_all([ceo,a,monitor]);db.flush()
        original=Email(mailbox_id=monitor.id,message_id="original",internet_message_id="<original>",conversation_id="thread",subject="Important request",sender="p@customer.com",receiver=a.email,received_time=datetime(2026,10,26,10,tzinfo=timezone.utc),folder="inbox",classification=Classification.CUSTOMER,status=EmailStatus.IGNORED,assigned_employee_id=ceo.id)
        db.add(original);db.flush()
        sync.reconcile_replies(db,[ceo,a]);db.flush()
        assert original.status==EmailStatus.PENDING
        assert original.assigned_employee_id==a.id
        reports={row["id"]:row for row in EmailRepository(db).employee_performance()}
        assert reports[a.id]["pending"]==1
        assert reports[ceo.id]["pending"]==0
        assert db.scalars(select(Mailbox)).all()==[monitor]
    engine.dispose()


def test_to_discovery_reuses_existing_addresses_and_preserves_inactive_employees():
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        existing=Employee(name="Existing",email="A@INDIANINFOTECH.ORG",active=True)
        inactive=Employee(name="Inactive",email="paused@indianinfotech.org",active=False)
        db.add_all([existing,inactive]);db.flush()
        recipients=[("New name"," a@indianinfotech.org "),("New Person","new@indianinfotech.org"),("Duplicate","NEW@INDIANINFOTECH.ORG"),("Do not reactivate","paused@indianinfotech.org"),("Invalid",""),("Customer","customer@outside.com"),("Spoofed domain","fake@indianinfotech.org.attacker.com"),("Subdomain","user@sub.indianinfotech.org")]
        active=sync._discover_to_employees(db,recipients)
        assert len(db.scalars(select(Employee)).all())==3
        assert existing.name=="Existing"
        assert inactive not in active and not inactive.active
        new=db.scalar(select(Employee).where(Employee.email=="new@indianinfotech.org"))
        assert new.name=="New Person"
        assert new in active
        sync._discover_to_employees(db,recipients)
        assert len(db.scalars(select(Employee)).all())==3
    engine.dispose()


def test_saved_ceo_mail_creates_missing_to_employee_and_assigns_pending():
    from datetime import datetime, timezone
    from app.models.entities import Classification, EmailStatus
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        ceo=Employee(name="CEO",email="ceo@indianinfotech.org",active=True)
        monitor=Mailbox(address=ceo.email,display_name="CEO",provider="gmail")
        db.add_all([ceo,monitor]);db.flush()
        email=Email(mailbox_id=monitor.id,message_id="saved",sender="p@customer.com",receiver="a@indianinfotech.org",subject="Important",received_time=datetime(2026,10,26,tzinfo=timezone.utc),folder="inbox",classification=Classification.CUSTOMER,status=EmailStatus.IGNORED)
        db.add(email);db.flush()
        sync.reconcile_replies(db,[ceo]);db.flush()
        employee=db.scalar(select(Employee).where(Employee.email=="a@indianinfotech.org"))
        assert employee is not None
        assert email.assigned_employee_id==employee.id
        assert email.status==EmailStatus.PENDING
        assert email.assigned_employee_id!=ceo.id
        sync.reconcile_replies(db,[ceo]);db.flush()
        assert len(db.scalars(select(Employee)).all())==2
    engine.dispose()


def test_external_employee_cleanup_preserves_company_records_and_mail_history():
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([Employee(name="Valid",email="Valid@INDIANINFOTECH.ORG",active=True),Employee(name="Removed",email="removed@indianinfotech.org",active=False),Employee(name="External",email="customer@outside.com",active=True),Employee(name="Fake",email="person@indianinfotech.org.attacker.com",active=True)])
        db.commit()
    migration=importlib.import_module("migrations.versions.0016_company_employee_domain")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
    with sessions() as db:
        employees={row.email:row for row in db.scalars(select(Employee))}
        assert len(employees)==4
        assert employees["Valid@INDIANINFOTECH.ORG"].active
        assert not employees["removed@indianinfotech.org"].active
        assert not employees["customer@outside.com"].active
        assert not employees["person@indianinfotech.org.attacker.com"].active
        sync._discover_to_employees(db,[("External again","customer@outside.com")])
        assert len(db.scalars(select(Employee)).all())==4
        assert not employees["customer@outside.com"].active
    engine.dispose()
