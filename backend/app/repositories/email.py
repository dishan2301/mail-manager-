from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import and_,case,func,or_,select
from sqlalchemy.orm import Session,joinedload,selectinload
from app.models.entities import Email,EmailRecipient,EmailStatus,Employee,Mailbox,SLATier

def employee_mail_scope(employee_id):
    return or_(Email.assigned_employee_id==employee_id,Email.responder_employee_id==employee_id,select(EmailRecipient.email_id).where(EmailRecipient.email_id==Email.id,EmailRecipient.employee_id==employee_id).correlate(Email,Employee).exists())


def employee_reply_credit(employee_id):
    return and_(Email.status==EmailStatus.REPLIED,Email.responder_employee_id==employee_id)


class EmailRepository:
    def __init__(self,db:Session):self.db=db
    def all_employee_reply_rate(self,mailbox_ids:list[int]|None=None):
        stmt=select(Email.internet_message_id,Email.mailbox_id,Email.message_id,Email.status).where(Email.folder=="inbox",Email.status.in_([EmailStatus.PENDING,EmailStatus.REPLIED]))
        if mailbox_ids is not None:stmt=stmt.where(Email.mailbox_id.in_(mailbox_ids))
        unique={}
        for internet_id,mailbox_id,message_id,status in self.db.execute(stmt):
            key=("internet",internet_id.strip().strip("<>").casefold()) if internet_id and internet_id.strip().strip("<>") else ("mailbox",mailbox_id,message_id)
            priority={EmailStatus.PENDING:1,EmailStatus.REPLIED:2}
            if key not in unique or priority[status]>priority[unique[key]]:unique[key]=status
        replied=sum(status==EmailStatus.REPLIED for status in unique.values());pending=sum(status==EmailStatus.PENDING for status in unique.values());received=len(unique)
        return {"replied":replied,"pending":pending,"total_incoming":received,"reply_rate":round(replied*100/received) if received else 0}
    def pending(self,page=1,page_size=25,status=None,mailbox=None,employee=None,search=None,date_filter=None,mailbox_ids:list[int]|None=None):
        stmt=select(Email).options(joinedload(Email.mailbox),joinedload(Email.employee),selectinload(Email.recipients).joinedload(EmailRecipient.employee));count=select(func.count()).select_from(Email)
        filters=[]
        if mailbox_ids is not None:filters.append(Email.mailbox_id.in_(mailbox_ids))
        if status:
            if status.lower() in {x.value for x in SLATier}:filters.append(Email.sla_tier==SLATier(status.lower()))
            elif status.lower() in {x.value for x in EmailStatus}:filters.append(Email.status==EmailStatus(status.lower()))
        if mailbox:filters.append(Email.mailbox_id==mailbox)
        if employee:filters.append(employee_mail_scope(employee))
        if search:
            term=f"%{search}%"
            searchable=[Email.sender.ilike(term),Email.subject.ilike(term),Email.receiver.ilike(term),Email.employee.has(Employee.name.ilike(term)),Email.employee.has(Employee.email.ilike(term)),Email.mailbox.has(Mailbox.address.ilike(term)),Email.mailbox.has(Mailbox.display_name.ilike(term))]
            normalized=search.strip().lower()
            if normalized in {x.value for x in EmailStatus}:searchable.append(Email.status==EmailStatus(normalized))
            if normalized in {x.value for x in SLATier}:searchable.append(Email.sla_tier==SLATier(normalized))
            try:
                searched_date=datetime.fromisoformat(search.strip()).replace(tzinfo=timezone.utc)
                searchable.append(and_(Email.received_time>=searched_date,Email.received_time<searched_date+timedelta(days=1)))
            except ValueError:pass
            filters.append(or_(*searchable))
        now=datetime.now(timezone.utc)
        if date_filter=="today":filters.append(Email.received_time>=now.replace(hour=0,minute=0,second=0,microsecond=0))
        elif date_filter=="yesterday":
            today=now.replace(hour=0,minute=0,second=0,microsecond=0);filters.extend([Email.received_time>=today-timedelta(days=1),Email.received_time<today])
        elif date_filter=="week":filters.append(Email.received_time>=now-timedelta(days=7))
        stmt=stmt.where(*filters);count=count.where(*filters);total=self.db.scalar(count) or 0
        status_order=case((Email.status==EmailStatus.PENDING,0),(Email.status==EmailStatus.REPLIED,1),else_=2)
        urgency_order=case((Email.sla_tier==SLATier.CRITICAL,0),(Email.sla_tier==SLATier.OVERDUE,1),(Email.sla_tier==SLATier.WARNING,2),else_=3)
        order=(status_order,urgency_order,Email.pending_hours.desc(),Email.received_time.asc(),Email.id.asc())
        return list(self.db.scalars(stmt.order_by(*order).offset((page-1)*page_size).limit(page_size)).unique()),total
    def employee_performance(self,mailbox_ids:list[int]|None=None):
        join=employee_mail_scope(Employee.id)
        if mailbox_ids is not None:join=and_(join,Email.mailbox_id.in_(mailbox_ids))
        rows=self.db.execute(select(Employee.id,Employee.name,Employee.department,func.count(Email.id),func.sum(case((employee_reply_credit(Employee.id),1),else_=0)),func.avg(case((employee_reply_credit(Employee.id),Email.pending_hours),else_=None)),func.sum(case((Email.status==EmailStatus.PENDING,1),else_=0)),func.sum(case((and_(Email.status==EmailStatus.PENDING,Email.sla_tier==SLATier.CRITICAL),1),else_=0)),func.sum(case((and_(Email.status==EmailStatus.PENDING,Email.sla_tier==SLATier.WARNING),1),else_=0)),func.sum(case((and_(Email.status==EmailStatus.PENDING,Email.sla_tier==SLATier.HEALTHY),1),else_=0)),func.sum(case((Email.status==EmailStatus.IGNORED,1),else_=0)),func.sum(case((and_(Email.status==EmailStatus.REPLIED,or_(Email.responder_employee_id.is_(None),Email.responder_employee_id!=Employee.id)),1),else_=0))).outerjoin(Email,join).where(Employee.active.is_(True),func.lower(func.trim(Employee.email)).like("%@indianinfotech.org")).group_by(Employee.id,Employee.name,Employee.department)).all()
        return [{"id":r[0],"employee":r[1],"department":r[2],"total":r[3] or 0,"received":r[3] or 0,"replied":r[4] or 0,"average_reply_time":float(r[5] or 0),"pending":r[6] or 0,"critical":r[7] or 0,"warning":r[8] or 0,"healthy":r[9] or 0,"ignored":r[10] or 0,"resolved":r[4] or 0,"replied_by_other":r[11] or 0} for r in rows]
    def employee_connections(self,mailbox_ids:list[int]|None=None,limit:int=8):
        join=employee_mail_scope(Employee.id)
        filters=[] if mailbox_ids is None else [Email.mailbox_id.in_(mailbox_ids)]
        rows=self.db.execute(select(Email.sender,Employee.name,func.count(Email.id),func.sum(case((Email.status==EmailStatus.PENDING,1),else_=0)),func.sum(case((employee_reply_credit(Employee.id),1),else_=0))).join(Employee,join).where(*filters).group_by(Email.sender,Employee.name).order_by(func.count(Email.id).desc()).limit(limit)).all()
        return [{"sender":r[0],"employee":r[1],"total":r[2] or 0,"pending":r[3] or 0,"replied":r[4] or 0} for r in rows]
    def employee_trend(self,employee_id:int,days:int|None=14,mailbox_ids:list[int]|None=None,year:int|None=None):
        cutoff=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=(days or 1)-1)
        filters=[employee_mail_scope(employee_id),Email.folder=="inbox"]
        if year is not None:
            start=datetime(year,1,1,tzinfo=timezone.utc);end=datetime(year+1,1,1,tzinfo=timezone.utc)
            filters.extend([Email.received_time>=start,Email.received_time<end])
        elif days is not None:filters.append(Email.received_time>=cutoff)
        if mailbox_ids is not None:filters.append(Email.mailbox_id.in_(mailbox_ids))
        rows=self.db.execute(select(func.date(Email.received_time),func.count(Email.id),func.sum(case((employee_reply_credit(employee_id),1),else_=0)),func.sum(case((Email.status==EmailStatus.PENDING,1),else_=0)),func.sum(case((Email.status==EmailStatus.IGNORED,1),else_=0)),func.sum(case((and_(Email.status==EmailStatus.REPLIED,or_(Email.responder_employee_id.is_(None),Email.responder_employee_id!=employee_id)),1),else_=0))).where(*filters).group_by(func.date(Email.received_time))).all()
        if days is None and year is None:return [{"date":str(r[0]),"received":r[1],"replied":r[2],"pending":r[3],"ignored":r[4],"replied_by_other":r[5]} for r in rows]
        if year is not None:
            start=datetime(year,1,1,tzinfo=timezone.utc);days_in_year=(datetime(year+1,1,1,tzinfo=timezone.utc)-start).days
            cutoff=start;days=days_in_year
        values={str(r[0]):r for r in rows};result=[]
        for offset in range(days):
            day=(cutoff+timedelta(days=offset)).date().isoformat();r=values.get(day)
            result.append({"date":day,"received":r[1] if r else 0,"replied":r[2] if r else 0,"pending":r[3] if r else 0,"ignored":r[4] if r else 0,"replied_by_other":r[5] if r else 0})
        return result
    def employee_hourly_activity(self,employee_id:int,day:date,mailbox_ids:list[int]|None=None):
        start=datetime(day.year,day.month,day.day,tzinfo=timezone.utc)-timedelta(days=1)
        end=start+timedelta(days=3)
        filters=[employee_mail_scope(employee_id),Email.folder=="inbox",Email.received_time>=start,Email.received_time<end]
        if mailbox_ids is not None:filters.append(Email.mailbox_id.in_(mailbox_ids))
        rows=self.db.execute(select(Email.received_time,Email.status,Mailbox.timezone,Email.responder_employee_id).join(Mailbox,Mailbox.id==Email.mailbox_id).where(*filters)).all()
        buckets={slot:{"slot":slot,"received":0,"replied":0,"pending":0} for slot in range(48)}
        for received_time,status,timezone_name,responder_id in rows:
            local_time=received_time.replace(tzinfo=timezone.utc) if received_time.tzinfo is None else received_time
            try:local_time=local_time.astimezone(ZoneInfo(timezone_name or "UTC"))
            except Exception:local_time=local_time.astimezone(timezone.utc)
            if local_time.date()!=day:continue
            slot=(local_time.hour*60+local_time.minute)//30
            buckets[slot]["received"]+=1
            if status==EmailStatus.REPLIED and responder_id==employee_id:buckets[slot]["replied"]+=1
            elif status==EmailStatus.PENDING:buckets[slot]["pending"]+=1
        return list(buckets.values())
    def employee_daily_senders(self,employee_id:int,day:date,mailbox_ids:list[int]|None=None):
        start=datetime(day.year,day.month,day.day,tzinfo=timezone.utc)
        end=start+timedelta(days=1)
        filters=[employee_mail_scope(employee_id),Email.folder=="inbox",Email.received_time>=start,Email.received_time<end]
        if mailbox_ids is not None:filters.append(Email.mailbox_id.in_(mailbox_ids))
        rows=self.db.execute(select(Email.sender,func.count(Email.id)).where(*filters).group_by(Email.sender).order_by(func.count(Email.id).desc(),Email.sender.asc())).all()
        return [{"sender":sender,"count":count} for sender,count in rows]
    def sender_insights(self,mailbox_ids:list[int]|None=None,limit:int=8):
        filters=[] if mailbox_ids is None else [Email.mailbox_id.in_(mailbox_ids)]
        rows=self.db.execute(select(Email.sender,func.count(Email.id),func.sum(case((Email.status==EmailStatus.REPLIED,1),else_=0)),func.sum(case((Email.status==EmailStatus.PENDING,1),else_=0)),func.sum(case((Email.status==EmailStatus.IGNORED,1),else_=0))).where(*filters).group_by(Email.sender).order_by(func.count(Email.id).desc()).limit(limit)).all()
        return [{"sender":r[0],"total":r[1] or 0,"replied":r[2] or 0,"pending":r[3] or 0,"ignored":r[4] or 0,"reply_rate":round(((r[2] or 0)/(r[1] or 1))*100,1)} for r in rows]
