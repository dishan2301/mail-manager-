import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
import hashlib
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import AIReviewSetting, Classification, ConversationAIReview, Email, EmailStatus, SecurityAuditEvent
from app.services.gmail import GmailDeltaSync
from app.services.graph import DelegatedGraphDeltaSync, GraphDeltaSync, delegated_authority_tenant
from app.services.security_events import audit
from app.services.secrets import get_mailbox_token, set_mailbox_token,mailbox_graph_settings
from app.services.writing_assistant import WritingAssistantError, review_employee_conversations
from app.services.review_rubric import score_saved_review
from app.services.ai_provider import active_ai_settings

logger = logging.getLogger(__name__)
REVIEW_VERSION = 2


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _conversation_key(email: Email) -> str:
    return email.conversation_id or f"message:{hashlib.sha256(email.message_id.encode()).hexdigest()}"


def _thread_rows(db, mailbox_id: int, key: str, incoming: list[Email]) -> list[Email]:
    if not key.startswith("message:"):
        return list(db.scalars(select(Email).options(joinedload(Email.mailbox)).where(Email.mailbox_id == mailbox_id, Email.conversation_id == key, Email.folder.in_(["inbox", "sentitems"])).order_by(Email.received_time, Email.id)))
    message = incoming[0]
    rows = [message]
    internet_id = (message.internet_message_id or "").strip().strip("<>").casefold()
    if internet_id:
        outgoing = db.scalars(select(Email).options(joinedload(Email.mailbox)).where(Email.mailbox_id == mailbox_id, Email.folder.in_(["inbox", "sentitems"])))
        for email in outgoing:
            references = {part.strip().strip("<>").casefold() for part in (email.references or "").split()}
            in_reply_to = (email.in_reply_to or "").strip().strip("<>").casefold()
            if in_reply_to == internet_id or internet_id in references:
                rows.append(email)
    return sorted(rows, key=lambda email: _utc(email.sent_time or email.received_time))


def _last_activity(thread: list[Email]) -> datetime:
    return max(_utc(value) for message in thread for value in (message.received_time, message.sent_time, message.replied_at) if value is not None)


def _ai_assistance(db, thread: list[Email]) -> list[dict]:
    events = db.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.object_type == "email", SecurityAuditEvent.object_id.in_([str(message.id) for message in thread]), SecurityAuditEvent.action == "email.reply.assist", SecurityAuditEvent.outcome == "success").order_by(SecurityAuditEvent.created_at, SecurityAuditEvent.id))
    return [{"date": _utc(event.created_at).isoformat(), "actor_user_id": event.actor_user_id, "mode": event.details.get("mode"), "has_employee_draft": event.details.get("has_employee_draft"), "input_word_count": event.details.get("input_word_count"), "sent_usage_verified": False} for event in events]


def _review_activity(db, thread: list[Email]) -> datetime:
    assisted_at = db.scalar(select(func.max(SecurityAuditEvent.created_at)).where(SecurityAuditEvent.object_type == "email", SecurityAuditEvent.object_id.in_([str(message.id) for message in thread]), SecurityAuditEvent.action == "email.reply.assist", SecurityAuditEvent.outcome == "success"))
    return max(_last_activity(thread), _utc(assisted_at)) if assisted_at else _last_activity(thread)


def _strategy(email: Email, settings):
    token = get_mailbox_token(email.mailbox, settings)
    if email.mailbox.provider == "gmail":
        if not token:
            raise RuntimeError("Gmail mailbox is not connected")
        return GmailDeltaSync(settings, token), token
    settings=mailbox_graph_settings(email.mailbox,settings)
    strategy = DelegatedGraphDeltaSync(settings, token, delegated_authority_tenant(email.mailbox.address, settings)) if token else GraphDeltaSync(settings)
    return strategy, token


def _save_token(email: Email, strategy, previous: str | None, settings) -> None:
    if email.mailbox.provider == "microsoft" and previous and strategy.latest_refresh_token != previous:
        set_mailbox_token(email.mailbox, strategy.latest_refresh_token, settings)

async def _save_rubric(review:ConversationAIReview,settings)->None:
    try:
        review.rubric=await score_saved_review(settings,review.analysis)
    except Exception as exc:
        review.rubric={"retry_after":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        logger.warning("Rubric unavailable for review %s (%s)",review.id,type(exc).__name__)
    review.rubric={**(review.rubric or {}),"review_version":REVIEW_VERSION}


async def review_new_or_changed_conversations() -> dict:
    reviewed = failed = 0
    strategies = {}
    with SessionLocal() as db:
        settings = active_ai_settings(db,get_settings())
        if not settings.ai_api_key:
            return {"skipped": "AI provider is not configured", "reviewed": 0, "failed": 0}
        consent = db.get(AIReviewSetting, 1)
        if not consent or not consent.enabled:
            return {"skipped": "AI reviews are not enabled", "reviewed": 0, "failed": 0}
        now = datetime.now(ZoneInfo(settings.app_timezone))
        cutoff = min(now.replace(day=1,hour=0,minute=0,second=0,microsecond=0),now-timedelta(days=7)).astimezone(timezone.utc)
        incoming = list(db.scalars(select(Email).options(joinedload(Email.mailbox), joinedload(Email.employee), joinedload(Email.responder)).where(Email.folder == "inbox", Email.classification == Classification.CUSTOMER, or_(and_(Email.status==EmailStatus.PENDING,Email.assigned_employee_id.is_not(None)),and_(Email.status==EmailStatus.REPLIED,Email.responder_employee_id.is_not(None))), Email.received_time >= cutoff).order_by(Email.received_time, Email.id)))
        grouped: dict[tuple[int, str, int], list[Email]] = {}
        for email in incoming:
            grouped.setdefault((email.mailbox_id, _conversation_key(email), email.responder_employee_id if email.status==EmailStatus.REPLIED else email.assigned_employee_id), []).append(email)
        stored = {(row.mailbox_id, row.conversation_key, row.employee_id): row for row in db.scalars(select(ConversationAIReview))}
        # Review the newest customer conversations first. A single slow or
        # stale historical thread must not starve the current daily report.
        ordered_groups = sorted(grouped.items(), key=lambda item: (stored.get(item[0]).status == "failed" if stored.get(item[0]) else False, -_utc(item[1][0].received_time).timestamp()))
        for (mailbox_id, key, employee_id), messages_inbox in ordered_groups:
            db.refresh(consent)
            if not consent.enabled:return {"skipped":"AI reviews were disabled","reviewed":reviewed,"failed":failed}
            employee = messages_inbox[-1].responder if messages_inbox[-1].status==EmailStatus.REPLIED else messages_inbox[-1].employee
            if not employee:
                continue
            thread = _thread_rows(db, mailbox_id, key, messages_inbox)
            last_message = _review_activity(db,thread)
            replies = [_utc(message.replied_at) for message in thread if message.replied_at]
            sent = [_utc(message.sent_time or message.received_time) for message in thread if message.folder == "sentitems" or parseaddr(message.sender)[1].casefold()==employee.email.casefold()]
            if replies and (not sent or max(sent) < max(replies)-timedelta(minutes=2)):
                continue  # The in-app reply must sync before its content can be reviewed.
            first_received = min((_utc(message.received_time) for message in messages_inbox), default=last_message)
            review = stored.get((mailbox_id, key, employee_id))
            if review and review.status == "ready" and review.employee_id == employee.id and _utc(review.last_message_at) >= last_message and (review.rubric or {}).get("review_version")==REVIEW_VERSION:
                retry_after=(review.rubric or {}).get("retry_after")
                if review.analysis and len(review.analysis)>=300 and (review.rubric is None or "actionability" not in review.rubric or retry_after and datetime.fromisoformat(retry_after)<=datetime.now(timezone.utc)):
                    await _save_rubric(review,settings)
                    db.commit()
                continue
            if review and review.status == "failed" and _utc(review.last_message_at)>=last_message and review.analyzed_at and _utc(review.analyzed_at)+timedelta(minutes=1)>datetime.now(timezone.utc):
                continue
            if not review:
                review = ConversationAIReview(mailbox_id=mailbox_id, conversation_key=key, employee_id=employee.id, received_at=first_received, last_message_at=last_message, status="pending")
                db.add(review)
                db.flush()
                stored[(mailbox_id, key, employee_id)] = review
            review.employee_id = employee.id
            review.received_at = first_received
            review.last_message_at = last_message
            review.status = "pending"
            review.analysis = None
            review.rubric = None
            review.error_code = None
            db.commit()
            try:
                rendered_messages = []
                characters = 0
                analysis = None
                assistance = _ai_assistance(db,thread)
                async def analyze_section():
                    db.refresh(consent)
                    if not consent.enabled:raise PermissionError("AI reviews were disabled")
                    return await review_employee_conversations(settings, employee.name, employee.department, "conversation review", [{"subject":messages_inbox[0].subject,"date":first_received.isoformat(),"messages":rendered_messages,"prior_review":analysis,"recorded_ai_assistance":assistance}])
                for message in thread:
                    if message.mailbox_id not in strategies:
                        strategies[message.mailbox_id] = _strategy(message, settings)
                    strategy, refresh_token = strategies[message.mailbox_id]
                    try:
                        body = await asyncio.wait_for(strategy.message_content(message.mailbox.address, message.message_id), timeout=15)
                    except Exception as exc:
                        # Do not let a slow mailbox provider starve all coaching
                        # reviews. NVIDIA can still produce a limited review
                        # from the synced metadata and must state the limitation.
                        logger.warning("Message body unavailable for review email %s: %s", message.id, type(exc).__name__)
                        body = "[Message body unavailable from the mailbox provider. Use only the synced subject, dates, sender, status, and other supplied metadata; mark content-based findings as insufficient evidence.]"
                    _save_token(message, strategy, refresh_token, settings)
                    speaker = "Employee" if parseaddr(message.sender)[1].casefold() == employee.email.casefold() else "Customer" if message.folder == "inbox" else "Unattributed outgoing"
                    for offset in range(0,max(1,len(body)),40000):
                        part = body[offset:offset+40000]
                        if rendered_messages and (characters+len(part)>40000 or len(rendered_messages)>=200):
                            analysis = await analyze_section()
                            rendered_messages = []
                            characters = 0
                        rendered_messages.append({"handled_by":speaker,"date":_utc(message.sent_time or message.received_time).isoformat(),"body":part,"message_part":offset//40000+1})
                        characters += len(part)
                if rendered_messages:analysis = await analyze_section()
                review.analysis = analysis
                if analysis and len(analysis)>=300:
                    await _save_rubric(review,settings)
                review.rubric={**(review.rubric or {}),"review_version":REVIEW_VERSION}
                review.status = "ready"
                review.analyzed_at = datetime.now(timezone.utc)
                review.error_code = None
                reviewed += 1
                audit(db, None, "report.ai_review.daily", "success", object_type="employee", object_id=employee.id, details={"mailbox_id":mailbox_id,"messages":len(thread)})
            except Exception as exc:
                if isinstance(exc,PermissionError):
                    review.status="pending";db.commit()
                    return {"skipped":"AI reviews were disabled","reviewed":reviewed,"failed":failed}
                review.status = "failed"
                review.analyzed_at = datetime.now(timezone.utc)
                review.error_code = f"ai_provider_http_{exc.status_code}" if isinstance(exc,WritingAssistantError) and exc.status_code else "ai_response_error" if isinstance(exc,WritingAssistantError) else "mailbox_error" if isinstance(exc,RuntimeError) else type(exc).__name__[:80]
                failed += 1
                audit(db, None, "report.ai_review.daily", "failed", object_type="employee", object_id=employee.id, details={"mailbox_id":mailbox_id,"reason":review.error_code})
                logger.warning("Daily conversation review failed for employee %s in mailbox %s (%s)", employee.id, mailbox_id, review.error_code)
            db.commit()
    return {"reviewed": reviewed, "failed": failed}
