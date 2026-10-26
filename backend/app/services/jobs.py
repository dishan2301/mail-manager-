import logging
import asyncio
from datetime import datetime,timezone
from html import escape

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Email,EmailStatus,EscalationEvent,SLARule,SLATier,User,Role,Mailbox,MailboxStatus,SyncLog
from app.services.content import content as ui_text
from app.services.notifications import send_html
from app.services.sync import sync_all_mailboxes
from app.services.conversation_reviews import review_new_or_changed_conversations
from app.services.sync_health import mailbox_freshness
from app.services.ai_provider import run_saved_ai_connection_check


logger=logging.getLogger(__name__)


async def _run_with_lease(name:str,operation,timeout:int):
    settings=get_settings();redis=Redis.from_url(settings.redis_url);lock=redis.lock(name,timeout=timeout,blocking_timeout=0);acquired=False
    try:
        acquired=bool(await asyncio.to_thread(lock.acquire,blocking=False))
    except RedisError:
        if settings.environment.lower()!="development":raise
        logger.warning("Redis unavailable; running development job without distributed lock");return await operation()
    if not acquired:return False
    stop=asyncio.Event()
    async def renew():
        while True:
            try:await asyncio.wait_for(stop.wait(),timeout=max(1,min(30,timeout//3)));return True
            except TimeoutError:pass
            try:
                if not await asyncio.to_thread(lock.extend,timeout,replace_ttl=True):return False
            except RedisError:return False
    worker=asyncio.create_task(operation());heartbeat=asyncio.create_task(renew())
    try:
        done,_=await asyncio.wait({worker,heartbeat},return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done and not heartbeat.result() and not worker.done():worker.cancel();await asyncio.gather(worker,return_exceptions=True);raise RuntimeError(f"Lost distributed lease {name}")
        result=await worker;stop.set();await heartbeat;return result
    finally:
        stop.set()
        try:await asyncio.to_thread(lock.release)
        except RedisError:logger.warning("Unable to release Redis job lock",exc_info=True)


async def run_sync_with_lease():
    async def operation():await sync_all_mailboxes();process_escalations();process_sync_health_alerts();return True
    return await _run_with_lease("oeis:mailbox-sync",operation,max(300,get_settings().sync_interval_seconds*2))


async def sync_job():return await run_sync_with_lease()


def process_sync_health_alerts():
    settings=get_settings();now=datetime.now(timezone.utc)
    threshold=max(60,getattr(settings,"sync_stale_after_seconds",900))
    with SessionLocal() as db:
        admins=list(db.scalars(select(User).where(User.role==Role.ADMIN,User.active.is_(True))))
        if not admins:return
        for mailbox in db.scalars(select(Mailbox).where(Mailbox.status!=MailboxStatus.PAUSED)):
            if not mailbox_freshness(mailbox,threshold,now)["stale"]:continue
            sent=db.scalar(select(SyncLog.id).where(SyncLog.mailbox_id==mailbox.id,SyncLog.action=="sync_stale_alert",SyncLog.started_at>mailbox.last_synced_at).limit(1))
            if sent:continue
            subject="OEIS mailbox sync is stale"
            body=f"<p>Mailbox {escape(mailbox.address)} last synced at {escape(str(mailbox.last_synced_at))} UTC. Dashboard counts may be incomplete.</p>"
            try:
                if not all(send_html(admin.email,subject,body) for admin in admins):continue
            except Exception:
                logger.warning("Could not send stale sync alert for mailbox %s",mailbox.id,exc_info=True)
                continue
            db.add(SyncLog(mailbox_id=mailbox.id,action="sync_stale_alert",started_at=now,finished_at=now,status="alert_sent"))
            db.commit()


def process_escalations():
    settings=get_settings();now=datetime.now(timezone.utc)
    pending_url=f"{settings.dashboard_url.rstrip('/')}?view=pending"
    with SessionLocal() as db:
        rules=list(db.scalars(select(SLARule)))
        manager_at=min((x.notify_manager_at_hours for x in rules if x.notify_manager_at_hours is not None),default=8)
        director_at=min((x.notify_director_at_hours for x in rules if x.notify_director_at_hours is not None),default=24)
        pending=list(db.scalars(select(Email).where(Email.status==EmailStatus.PENDING)))
        for email in pending:
            managers=[x.email for x in db.scalars(select(User).where(User.role==Role.MANAGER,User.active.is_(True)))] or ([settings.manager_email] if settings.manager_email else [])
            thresholds=[(f"manager-{manager_at:g}h",manager_at,"Manager",managers),(f"director-{director_at:g}h",director_at,"Director",[settings.director_email] if settings.director_email else [])]
            for name,hours,role,addresses in thresholds:
                exists=db.scalar(select(EscalationEvent).where(EscalationEvent.email_id==email.id,EscalationEvent.threshold==name))
                if email.pending_hours<hours or exists:continue
                title=ui_text(db,"notification.escalation.title",role=escape(role))
                body=ui_text(db,"notification.escalation.body",subject=escape(email.subject),sender=escape(email.sender),hours=email.pending_hours,url=escape(pending_url,quote=True))
                subject=ui_text(db,"notification.escalation.subject",subject=email.subject)
                delivered=bool(addresses) and all(send_html(address,subject,f"<h2>{title}</h2>{body}") for address in addresses)
                if delivered:
                    db.add(EscalationEvent(email_id=email.id,threshold=name,recipient_role=role,created_at=now))
                    db.commit()


def _summary_html(db,name:str,pending:list[Email],critical:int,overdue:int,average_text:str,dashboard_link:str)->str:
    top="".join(f"<li>{escape(email.sender)} - {escape(email.subject)}</li>" for email in pending[:3])
    greeting=ui_text(db,"notification.summary.greeting",name=escape(name)).strip()
    return ui_text(db,"notification.summary.body",greeting=greeting,pending=len(pending),critical=critical,overdue=overdue,average=escape(average_text),top=top,url=escape(dashboard_link,quote=True))


def _daily_summary_job(recipient_email:str|None=None):
    settings=get_settings();dashboard_link=f"{settings.dashboard_url.rstrip('/')}?view=pending"
    with SessionLocal() as db:
        pending=list(db.scalars(select(Email).where(Email.status==EmailStatus.PENDING).order_by(Email.pending_hours.desc())))
        replied=list(db.scalars(select(Email).where(Email.status==EmailStatus.REPLIED)))
        critical=sum(email.sla_tier==SLATier.CRITICAL for email in pending)
        overdue=sum(email.sla_tier==SLATier.OVERDUE for email in pending)
        average=sum(email.pending_hours for email in replied)/len(replied) if replied else 0
        hours=int(average);minutes=round((average-hours)*60);average_text=f"{hours} Hr {minutes} Min"
        if recipient_email:
            if not send_html(recipient_email,ui_text(db,"notification.summary.subject"),_summary_html(db,"",pending,critical,overdue,average_text,dashboard_link)):
                raise RuntimeError("No report delivery provider available")
            return
        managers=list(db.scalars(select(User).where(User.role==Role.MANAGER,User.active.is_(True))))
        if not managers and settings.manager_email:
            send_html(settings.manager_email,ui_text(db,"notification.summary.subject"),_summary_html(db,"",pending,critical,overdue,average_text,dashboard_link))
        if not managers and not settings.manager_email:
            managers=list(db.scalars(select(User).where(User.role==Role.ADMIN,User.active.is_(True))))
        for manager in managers:
            send_html(manager.email,ui_text(db,"notification.summary.subject"),_summary_html(db,manager.name,pending,critical,overdue,average_text,dashboard_link))


async def daily_summary_job(recipient_email:str|None=None):
    async def operation():await asyncio.to_thread(_daily_summary_job,recipient_email);return True
    return await _run_with_lease("oeis:daily-summary",operation,300)


async def conversation_ai_review_job():
    return await _run_with_lease("oeis:conversation-ai-review",review_new_or_changed_conversations,6*60*60)


async def daily_ai_connection_job():
    async def operation():
        with SessionLocal() as db:
            await run_saved_ai_connection_check(db)
        return True
    return await _run_with_lease("oeis:daily-ai-connection", operation, 60)
