from datetime import date,datetime,time,timezone
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import BusinessCalendar,ClassificationRule,Email,EmailStatus,Employee,Mailbox,MailboxStatus,SLARule,SLATier,SyncLog
from app.services.classification import Rule,classify
from app.services.graph import DelegatedGraphDeltaSync,GraphDeltaSync,delegated_authority_tenant
from app.services.gmail import GmailDeltaSync
from app.services.sla import Calendar,elapsed_hours,tier_for
from app.services.reply_detection import MessageRef,is_reply
from app.services.secrets import get_mailbox_token,set_mailbox_token

def _text(value,max_length:int)->str:return str(value or "")[:max_length]
def _headers(item:dict)->dict[str,str]:return {_text(h.get("name"),120).lower():_text(h.get("value"),8000) for h in item.get("internetMessageHeaders",[])[:200]}
def _recipients(item:dict,fallback:str)->str:
    addresses=[row.get("emailAddress",{}).get("address") for row in item.get("toRecipients",[])]
    return _text(", ".join(address for address in addresses if address) or fallback,320)
def _assignee(receiver:str, mailbox_address:str, employees:list[Employee])->int|None:
    by_address={employee.email.strip().lower():employee.id for employee in employees if employee.active}
    for address in [mailbox_address,*receiver.replace(";",",").split(",")]:
        employee_id=by_address.get(address.strip().lower())
        if employee_id is not None:return employee_id
    return None
def _transient_sync_error(exc:Exception)->bool:
    message=f"{type(exc).__name__}: {exc}".lower()
    return any(token in message for token in ("nameresolutionerror","temporary failure","failed to resolve","httpsconnectionpool","connectionerror","connecttimeout","readtimeout","network is unreachable"))
async def sync_all_mailboxes():
    settings=get_settings()
    with SessionLocal() as db:
        accounts=list(db.scalars(select(Mailbox).where(Mailbox.status!=MailboxStatus.PAUSED)))
        configured=[Rule(x.priority,x.field,x.pattern,x.classification) for x in db.scalars(select(ClassificationRule).where(ClassificationRule.active.is_(True)))]
        employees=list(db.scalars(select(Employee).where(Employee.active.is_(True)).order_by(Employee.id)))
        sla_rules=list(db.scalars(select(SLARule)));thresholds={x.tier:x.threshold_hours for x in sla_rules};business_only=all(x.business_hours_only for x in sla_rules) if sla_rules else True
        for mailbox in accounts:
            started=datetime.now(timezone.utc);fetched=new=0;error=None
            try:
                calendar_row=db.scalar(select(BusinessCalendar).where(BusinessCalendar.mailbox_id==mailbox.id)) or db.scalar(select(BusinessCalendar).where(BusinessCalendar.mailbox_id.is_(None)))
                calendar=Calendar(timezone=mailbox.timezone,start=time.fromisoformat(calendar_row.workday_start) if calendar_row else time(9),end=time.fromisoformat(calendar_row.workday_end) if calendar_row else time(18),weekdays=tuple(calendar_row.weekdays) if calendar_row else (0,1,2,3,4),holidays=frozenset(date.fromisoformat(x) for x in calendar_row.holidays) if calendar_row else frozenset())
                now=datetime.now(timezone.utc)
                existing_pending=list(db.scalars(select(Email).where(Email.mailbox_id==mailbox.id,Email.status==EmailStatus.PENDING)))
                for pending_email in existing_pending:
                    pending_email.pending_hours=elapsed_hours(pending_email.received_time,now,calendar,business_only);pending_email.sla_tier=tier_for(pending_email.pending_hours,thresholds or None)
                personal_domain=mailbox.address.lower().rsplit("@",1)[-1] in {"outlook.com","hotmail.com","live.com","msn.com"}
                refresh_token=get_mailbox_token(mailbox,settings)
                if mailbox.provider=="gmail":
                    if not refresh_token:raise RuntimeError("Click Connect Gmail and complete Google login before Sync")
                    strategy=GmailDeltaSync(settings,refresh_token)
                else:
                    if personal_domain and not refresh_token:raise RuntimeError("Click Connect Outlook and complete Microsoft login before Sync")
                    strategy=DelegatedGraphDeltaSync(settings,refresh_token,delegated_authority_tenant(mailbox.address,settings)) if refresh_token else GraphDeltaSync(settings)
                items,delta=await strategy.sync_mailbox(mailbox.address,mailbox.delta_link);fetched=len(items)
                if mailbox.provider=="microsoft" and refresh_token:mailbox.graph_auth_type="delegated";set_mailbox_token(mailbox,strategy.latest_refresh_token,settings)
                for item in items:
                    if "@removed" in item:continue
                    message_id=_text(item.get("id"),512)
                    if not message_id:continue
                    existing=db.scalar(select(Email).where(Email.mailbox_id==mailbox.id,Email.message_id==message_id))
                    sender=_text(item.get("from",{}).get("emailAddress",{}).get("address") or "unknown",320)
                    received=datetime.fromisoformat(item["receivedDateTime"].replace("Z","+00:00"));headers=_headers(item);classification=classify(sender,item.get("subject") or "",headers,configured)
                    pending=elapsed_hours(received,datetime.now(timezone.utc),calendar,business_only);tier=tier_for(pending,thresholds or None)
                    folder=item.get("_folder","unknown");sent_at=datetime.fromisoformat(item["sentDateTime"].replace("Z","+00:00")) if item.get("sentDateTime") else None
                    values={"conversation_id":_text(item.get("conversationId"),512) or None,"internet_message_id":_text(item.get("internetMessageId"),998) or None,"in_reply_to":_text(headers.get("in-reply-to"),998) or None,"references":_text(headers.get("references"),8000) or None,"thread_index":_text(item.get("conversationIndex"),8000) or None,"sender":sender,"receiver":_recipients(item,mailbox.address),"subject":_text(item.get("subject") or "(no subject)",4000),"received_time":received,"sent_time":sent_at,"folder":_text(folder,80),"categories":[_text(value,200) for value in item.get("categories",[])[:100]],"classification":classification,"status":EmailStatus.PENDING if folder=="inbox" and classification.value=="Customer" else EmailStatus.IGNORED,"pending_hours":pending,"sla_tier":tier}
                    if existing:
                        for key,value in values.items():setattr(existing,key,value)
                        if folder=="inbox" and existing.assigned_employee_id is None:
                            existing.assigned_employee_id=_assignee(values["receiver"],mailbox.address,employees)
                    else:
                        # Prefer the receiving mailbox owner, including delivery through CC, BCC or aliases.
                        if folder=="inbox":
                            values["assigned_employee_id"]=_assignee(values["receiver"],mailbox.address,employees)
                        db.add(Email(mailbox_id=mailbox.id,message_id=message_id,**values));new+=1
                db.flush();incoming=list(db.scalars(select(Email).where(Email.mailbox_id==mailbox.id,Email.status==EmailStatus.PENDING,Email.folder=="inbox")));sent=list(db.scalars(select(Email).where(Email.mailbox_id==mailbox.id,Email.folder=="sentitems")))
                for received_mail in incoming:
                    received_mail.pending_hours=elapsed_hours(received_mail.received_time,datetime.now(timezone.utc),calendar,business_only);received_mail.sla_tier=tier_for(received_mail.pending_hours,thresholds or None)
                    source=MessageRef(received_mail.internet_message_id,received_mail.conversation_id,received_mail.subject,received_mail.received_time)
                    for sent_mail in sent:
                        candidate=MessageRef(sent_mail.internet_message_id,sent_mail.conversation_id,sent_mail.subject,sent_mail.sent_time or sent_mail.received_time,sent_mail.in_reply_to,sent_mail.references)
                        if is_reply(source,candidate):received_mail.status=EmailStatus.REPLIED;received_mail.replied_at=candidate.timestamp;received_mail.pending_hours=elapsed_hours(received_mail.received_time,candidate.timestamp,calendar,business_only);break
                mailbox.delta_link=delta or mailbox.delta_link;mailbox.last_synced_at=datetime.now(timezone.utc);mailbox.last_sync_error=None;mailbox.status=MailboxStatus.ACTIVE;status="success"
            except Exception as exc:
                message=str(exc).strip() or "Synchronization failed"
                error=f"{type(exc).__name__}: {message}"
                if mailbox.last_synced_at and _transient_sync_error(exc):
                    mailbox.last_sync_error=f"Temporary sync issue: {error}"
                    mailbox.status=MailboxStatus.ACTIVE
                    status="warning"
                else:
                    mailbox.last_sync_error=error
                    mailbox.status=MailboxStatus.ERROR
                    status="failed"
            finished=datetime.now(timezone.utc);db.add(SyncLog(mailbox_id=mailbox.id,action=f"{mailbox.provider}_delta_sync",api_response=f"fetched={fetched};new={new}" if not error else None,errors=error,started_at=started,finished_at=finished,emails_fetched=fetched,emails_new=new,status=status));db.commit()
