from datetime import date,datetime,time,timezone
from email.utils import getaddresses
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import BusinessCalendar,ClassificationRule,Email,EmailRecipient,EmailStatus,Employee,Mailbox,MailboxStatus,SLARule,SLATier,SyncLog
from app.services.classification import Rule,classify
from app.services.employees import is_company_employee_email
from app.services.graph import DelegatedGraphDeltaSync,GraphDeltaSync,delegated_authority_tenant
from app.services.gmail import GmailDeltaSync
from app.services.sla import Calendar,elapsed_hours,tier_for
from app.services.reply_detection import MessageRef,is_reply
from app.services.secrets import get_mailbox_token,set_mailbox_token,mailbox_graph_settings

def _text(value,max_length:int)->str:return str(value or "")[:max_length]
def _headers(item:dict)->dict[str,str]:return {_text(h.get("name"),120).lower():_text(h.get("value"),8000) for h in item.get("internetMessageHeaders",[])[:200]}
def _recipients(item:dict,fallback:str)->str:
    addresses=[row.get("emailAddress",{}).get("address") for row in item.get("toRecipients",[])]
    return _text(", ".join(address for address in addresses if address),320)
def _assignee(receiver:str, mailbox_address:str, employees:list[Employee])->int|None:
    by_address={employee.email.strip().lower():employee.id for employee in employees if employee.active}
    for address in receiver.replace(";",",").split(","):
        employee_id=by_address.get(address.strip().lower())
        if employee_id is not None:return employee_id
    return None
def _discover_to_employees(db,recipients):
    existing=list(db.scalars(select(Employee).order_by(Employee.id)))
    for employee in existing:
        if not is_company_employee_email(employee.email):employee.active=False
    by_address={row.email.strip().casefold():row for row in existing}
    for name,address in recipients:
        address=address.strip().casefold()
        if len(address)>320 or not is_company_employee_email(address):continue
        if address in by_address:continue
        employee=Employee(name=_text(name.strip() or address.split("@",1)[0],120),email=address,department="General",active=True)
        db.add(employee);existing.append(employee);by_address[address]=employee
    db.flush()
    return [row for row in existing if row.active]
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
                mailbox_settings=mailbox_graph_settings(mailbox,settings) if mailbox.provider=="microsoft" else settings
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
                    strategy=DelegatedGraphDeltaSync(mailbox_settings,refresh_token,delegated_authority_tenant(mailbox.address,mailbox_settings)) if refresh_token else GraphDeltaSync(mailbox_settings)
                items,delta=await strategy.sync_mailbox(mailbox.address,mailbox.delta_link);fetched=len(items)
                if mailbox.provider=="microsoft" and refresh_token:mailbox.graph_auth_type="delegated";set_mailbox_token(mailbox,strategy.latest_refresh_token,settings)
                employees=_discover_to_employees(db,[(recipient.get("emailAddress",{}).get("name") or "",recipient.get("emailAddress",{}).get("address") or "") for item in items if item.get("_folder")=="inbox" and "@removed" not in item for recipient in item.get("toRecipients",[])])
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
                        if existing.manually_ignored:values["status"]=EmailStatus.IGNORED
                        for key,value in values.items():setattr(existing,key,value)
                        if folder=="inbox" and existing.assigned_employee_id is None:
                            existing.assigned_employee_id=_assignee(values["receiver"],mailbox.address,employees)
                    else:
                        # Final reconciliation below excludes observer copies.
                        if folder=="inbox":
                            values["assigned_employee_id"]=_assignee(values["receiver"],mailbox.address,employees)
                        db.add(Email(mailbox_id=mailbox.id,message_id=message_id,**values));new+=1
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
        reconcile_replies(db,employees)
        db.commit()


def reconcile_replies(db,employees):
    """To recipients owe replies; the actual responding employee earns credit."""
    mailboxes={row.id:row for row in db.scalars(select(Mailbox))}
    rows=list(db.scalars(select(Email).order_by(Email.received_time,Email.id)))
    rows_by_id={row.id:row for row in rows}
    # Backfill To recipients from already saved messages, even on an empty delta sync.
    employees=_discover_to_employees(db,getaddresses([row.receiver.replace(";",",") for row in rows if row.folder=="inbox"]))
    employees_by_address={row.email.strip().casefold():row.id for row in employees if row.active}
    replies=[row for row in rows if row.sender.strip().casefold() in employees_by_address and row.classification.value=="Customer"]
    by_header={};by_conversation={}
    for reply in replies:
        for target in set((reply.references or "").split()+[(reply.in_reply_to or "").strip()]):
            if target:by_header.setdefault(target,[]).append(reply)
        if reply.conversation_id:by_conversation.setdefault((reply.mailbox_id,reply.conversation_id),[]).append(reply)
    groups={}
    for row in rows:
        if row.folder!="inbox" or row.classification.value!="Customer":continue
        key=("message",row.internet_message_id.strip().casefold()) if row.internet_message_id else ("local",row.mailbox_id,row.message_id)
        groups.setdefault(key,[]).append(row)
    calendars={row.mailbox_id:row for row in db.scalars(select(BusinessCalendar))}
    rules=list(db.scalars(select(SLARule)))
    thresholds={row.tier:row.threshold_hours for row in rules}
    business_only=all(row.business_hours_only for row in rules) if rules else True
    response_ids=set()
    recipients_by_email={}
    for recipient in db.scalars(select(EmailRecipient)):
        recipients_by_email.setdefault(recipient.email_id,[]).append(recipient)
    for copies in groups.values():
        direct=[row for row in copies if mailboxes[row.mailbox_id].address.strip().casefold() in {address.strip().casefold() for address in row.receiver.replace(";",",").split(",")}]
        primary=(direct or copies)[0]
        owner_id=primary.assigned_employee_id if primary.assignment_overridden or primary.status==EmailStatus.REPLIED else None
        manual_reply=rows_by_id.get(primary.reply_email_id) if primary.reply_link_source=="manual" else None
        source=MessageRef(primary.internet_message_id,primary.conversation_id,primary.subject,primary.received_time)
        matches=[]
        copy_ids={row.id for row in copies}
        candidates={reply.id:reply for reply in by_header.get((primary.internet_message_id or "").strip(),[])}
        for copy in copies:
            for reply in by_conversation.get((copy.mailbox_id,copy.conversation_id),[]):candidates[reply.id]=reply
        for reply in candidates.values():
            if reply.id in copy_ids or reply.sender.strip().casefold()==primary.sender.strip().casefold():continue
            # Header links work across mailboxes; conversation IDs are mailbox scoped.
            local_source=next((copy for copy in copies if copy.mailbox_id==reply.mailbox_id),primary)
            source=MessageRef(local_source.internet_message_id,local_source.conversation_id,local_source.subject,local_source.received_time)
            candidate=MessageRef(reply.internet_message_id,reply.conversation_id if reply.mailbox_id==local_source.mailbox_id else None,reply.subject,reply.sent_time or reply.received_time,reply.in_reply_to,reply.references)
            if _utc(candidate.timestamp)>=_utc(source.timestamp) and is_reply(source,candidate):matches.append(reply)
        match=manual_reply if manual_reply and manual_reply.sender.strip().casefold() in employees_by_address and _utc(manual_reply.sent_time or manual_reply.received_time)>=_utc(primary.received_time) else min(matches,key=lambda row:_utc(row.sent_time or row.received_time)) if matches else None
        if match and match not in matches:matches.append(match)
        for response in matches:
            response_ids.add((response.internet_message_id or "").strip().casefold() or (response.mailbox_id,response.message_id))
        for row in copies:
            for recipient in recipients_by_email.get(row.id,[]):db.delete(recipient)
            row.status=(EmailStatus.IGNORED if row.manually_ignored else EmailStatus.DUPLICATE_COPY if row is not primary and mailboxes[row.mailbox_id].address.strip().casefold() in {address.strip().casefold() for address in row.receiver.replace(";",",").split(",")} else EmailStatus.OBSERVER_COPY if row.classification.value=="Customer" else EmailStatus.IGNORED)
            row.assigned_employee_id=None;row.responder_employee_id=None;row.replied_at=None;row.pending_hours=0
            if row is not primary:row.reply_email_id=None;row.reply_link_source=None
        if primary.manually_ignored:continue
        if _assignee(primary.receiver,"",employees) is None and match is None:continue
        to_ids={employees_by_address[address.strip().casefold()] for address in primary.receiver.replace(";",",").split(",") if address.strip().casefold() in employees_by_address}
        for employee_id in to_ids:db.add(EmailRecipient(email_id=primary.id,employee_id=employee_id))
        primary.status=EmailStatus.REPLIED if match else EmailStatus.PENDING
        primary.assigned_employee_id=owner_id if primary.assignment_overridden else owner_id or _assignee(primary.receiver,mailboxes[primary.mailbox_id].address,employees)
        primary.responder_employee_id=employees_by_address[match.sender.strip().casefold()] if match else None
        primary.reply_email_id=match.id if match else None
        primary.reply_link_source=("manual" if manual_reply is match else "automatic") if match else None
        primary.replied_at=(match.sent_time or match.received_time) if match else None
        mailbox=mailboxes[primary.mailbox_id];saved=calendars.get(mailbox.id) or calendars.get(None)
        calendar=Calendar(timezone=mailbox.timezone,start=time.fromisoformat(saved.workday_start) if saved else time(9),end=time.fromisoformat(saved.workday_end) if saved else time(18),weekdays=tuple(saved.weekdays) if saved else (0,1,2,3,4),holidays=frozenset(date.fromisoformat(value) for value in saved.holidays) if saved else frozenset())
        primary.pending_hours=elapsed_hours(primary.received_time,primary.replied_at or datetime.now(timezone.utc),calendar,business_only)
        primary.sla_tier=tier_for(primary.pending_hours,thresholds or None)
    db.flush()
    for row in rows:
        identity=(row.internet_message_id or "").strip().casefold() or (row.mailbox_id,row.message_id)
        if row.folder=="inbox" and identity in response_ids:
            for recipient in list(db.scalars(select(EmailRecipient).where(EmailRecipient.email_id==row.id))):db.delete(recipient)
            row.status=EmailStatus.IGNORED if row.manually_ignored else EmailStatus.OBSERVER_COPY;row.assigned_employee_id=None;row.responder_employee_id=None;row.replied_at=None;row.pending_hours=0;row.reply_email_id=None;row.reply_link_source=None


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
