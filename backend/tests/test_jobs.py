import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine,func,select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Classification,Email,EmailStatus,EscalationEvent,Mailbox,SLATier,SyncLog,User,Role
from app.services import jobs


def test_escalation_delivery_is_recorded_once_per_threshold(monkeypatch):
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(jobs,"SessionLocal",sessions)
    suffix=uuid4().hex
    with sessions() as db:
        mailbox=Mailbox(address=f"escalation-{suffix}@example.com",display_name="Escalation test",timezone="UTC")
        db.add(mailbox);db.flush()
        email=Email(mailbox_id=mailbox.id,message_id=f"message-{suffix}",sender="customer@example.com",receiver=mailbox.address,subject="Escalation acceptance",received_time=datetime.now(timezone.utc),folder="inbox",categories=[],classification=Classification.CUSTOMER,status=EmailStatus.PENDING,pending_hours=30,sla_tier=SLATier.CRITICAL)
        db.add(email);db.commit();db.refresh(email);email_id=email.id
    monkeypatch.setattr(jobs,"get_settings",lambda:SimpleNamespace(dashboard_url="https://oeis.example",manager_email="manager@example.com",director_email="director@example.com"))
    monkeypatch.setattr(jobs,"send_html",lambda *args,**kwargs:True)
    jobs.process_escalations();jobs.process_escalations()
    with sessions() as db:
        count=db.scalar(select(func.count()).select_from(EscalationEvent).where(EscalationEvent.email_id==email_id))
        assert count==2
    engine.dispose()


def test_stale_mailbox_alert_is_sent_once_until_next_success(monkeypatch):
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(jobs,"SessionLocal",sessions)
    sent=[]
    monkeypatch.setattr(jobs,"send_html",lambda address,subject,body: sent.append((address,subject,body)) or True)
    monkeypatch.setattr(jobs,"get_settings",lambda:SimpleNamespace(sync_stale_after_seconds=900))
    with sessions() as db:
        db.add(User(name="Admin",email="admin@example.com",password_hash="test",role=Role.ADMIN,active=True))
        db.add(Mailbox(address="stale@example.com",display_name="Stale",last_synced_at=datetime.now(timezone.utc)-timedelta(hours=2)))
        db.commit()
    jobs.process_sync_health_alerts();jobs.process_sync_health_alerts()
    with sessions() as db:
        alerts=list(db.scalars(select(SyncLog).where(SyncLog.action=="sync_stale_alert")))
    assert len(sent)==len(alerts)==1
    assert "stale@example.com" in sent[0][2]
    engine.dispose()


def test_distributed_lease_skips_duplicate_and_cancels_work_when_renewal_is_lost(monkeypatch):
    class FakeLock:
        def __init__(self,acquire:bool,extend:bool=True):self.acquire_result=acquire;self.extend_result=extend;self.released=False
        def acquire(self,blocking=False):return self.acquire_result
        def extend(self,*args,**kwargs):return self.extend_result
        def release(self):self.released=True
    class FakeRedis:
        def __init__(self,lock):self.value=lock
        def lock(self,*args,**kwargs):return self.value
    monkeypatch.setattr(jobs,"get_settings",lambda:SimpleNamespace(redis_url="redis://example",environment="production"))

    called=False;duplicate=FakeLock(False)
    async def should_not_run():
        nonlocal called;called=True
    monkeypatch.setattr(jobs.Redis,"from_url",lambda *_args,**_kwargs:FakeRedis(duplicate))
    assert asyncio.run(jobs._run_with_lease("duplicate",should_not_run,1)) is False and not called

    cancelled=False;lost=FakeLock(True,False)
    async def long_work():
        nonlocal cancelled
        try:await asyncio.sleep(10)
        except asyncio.CancelledError:cancelled=True;raise
    monkeypatch.setattr(jobs.Redis,"from_url",lambda *_args,**_kwargs:FakeRedis(lost))
    try:asyncio.run(jobs._run_with_lease("lost",long_work,1))
    except RuntimeError as exc:assert "Lost distributed lease" in str(exc)
    else:raise AssertionError("lease loss did not fail closed")
    assert cancelled and lost.released
