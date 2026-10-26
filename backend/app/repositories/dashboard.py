from datetime import datetime,timedelta,timezone
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.models.entities import Email,EmailStatus,SLATier
class DashboardRepository:
    def __init__(self,db:Session):self.db=db
    def kpis(self,mailbox_ids:list[int]|None=None)->dict:
        start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0);end=start+timedelta(days=1);scope=[] if mailbox_ids is None else [Email.mailbox_id.in_(mailbox_ids)];scalar=lambda stmt:self.db.scalar(stmt.where(*scope)) or 0
        return {"today_emails":scalar(select(func.count()).select_from(Email).where(Email.folder=="inbox",Email.received_time>=start,Email.received_time<end)),"pending_replies":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.PENDING)),"overdue":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.PENDING,Email.sla_tier==SLATier.OVERDUE)),"critical":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.PENDING,Email.sla_tier==SLATier.CRITICAL)),"average_reply_hours":scalar(select(func.avg(Email.pending_hours)).where(Email.status==EmailStatus.REPLIED)),"resolved_today":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.REPLIED,Email.replied_at>=start,Email.replied_at<end)),"ignored_emails":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.IGNORED)),"observer_copies":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.OBSERVER_COPY)),"duplicate_copies":scalar(select(func.count()).select_from(Email).where(Email.status==EmailStatus.DUPLICATE_COPY))}
