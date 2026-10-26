import enum
import hashlib
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Role(str, enum.Enum): ADMIN="admin"; MANAGER="manager"
class MailboxStatus(str, enum.Enum): ACTIVE="active"; PAUSED="paused"; ERROR="error"
class EmailStatus(str, enum.Enum): PENDING="pending"; REPLIED="replied"; IGNORED="ignored"; OBSERVER_COPY="observer_copy"; DUPLICATE_COPY="duplicate_copy"
class Classification(str, enum.Enum):
    IGNORE="Ignore"; AUTO_REPLY="Auto Reply"; NEWSLETTER="Newsletter"; MARKETING="Marketing"; SPAM="Spam"; OTP="OTP"; NO_REPLY="NoReply"; LINKEDIN="LinkedIn"; AMAZON="Amazon"; MICROSOFT="Microsoft Notifications"; GOOGLE="Google Alerts"; CUSTOMER="Customer"
class SLATier(str, enum.Enum): HEALTHY="healthy"; WARNING="warning"; OVERDUE="overdue"; CRITICAL="critical"


class User(Base):
    __tablename__="users"; id:Mapped[int]=mapped_column(primary_key=True); email:Mapped[str]=mapped_column(String(320),unique=True); name:Mapped[str]=mapped_column(String(120)); password_hash:Mapped[str]=mapped_column(String(255)); role:Mapped[Role]=mapped_column(Enum(Role)); active:Mapped[bool]=mapped_column(Boolean,default=True)
class Mailbox(Base):
    __tablename__="mailboxes"; id:Mapped[int]=mapped_column(primary_key=True); address:Mapped[str]=mapped_column(String(320),unique=True); display_name:Mapped[str]=mapped_column(String(120)); provider:Mapped[str]=mapped_column(String(20),default="microsoft"); status:Mapped[MailboxStatus]=mapped_column(Enum(MailboxStatus),default=MailboxStatus.ACTIVE); timezone:Mapped[str]=mapped_column(String(64),default="Asia/Kolkata"); delta_link:Mapped[str|None]=mapped_column(Text); graph_auth_type:Mapped[str]=mapped_column(String(20),default="application"); graph_refresh_token:Mapped[str|None]=mapped_column(Text); token_ciphertext:Mapped[str|None]=mapped_column(Text); token_nonce:Mapped[str|None]=mapped_column(String(64)); token_key_id:Mapped[str|None]=mapped_column(String(64)); azure_client_id:Mapped[str|None]=mapped_column(String(128)); azure_tenant_id:Mapped[str|None]=mapped_column(String(128)); azure_secret_ciphertext:Mapped[str|None]=mapped_column(Text); azure_secret_nonce:Mapped[str|None]=mapped_column(String(64)); azure_secret_key_id:Mapped[str|None]=mapped_column(String(64)); provider_subject_id:Mapped[str|None]=mapped_column(String(128)); provider_tenant_id:Mapped[str|None]=mapped_column(String(128)); last_synced_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); last_sync_error:Mapped[str|None]=mapped_column(Text)
    @property
    def graph_connected(self)->bool:return bool(self.graph_refresh_token or self.token_ciphertext)
    @property
    def connected(self)->bool:return bool(self.graph_refresh_token or self.token_ciphertext)
    @property
    def azure_secret_saved(self)->bool:return bool(self.azure_secret_ciphertext)
class Employee(Base):
    __tablename__="employees"; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(120)); email:Mapped[str]=mapped_column(String(320),unique=True); department:Mapped[str]=mapped_column(String(120),default="General"); active:Mapped[bool]=mapped_column(Boolean,default=True)
class Email(Base):
    __tablename__="emails"; __table_args__=(UniqueConstraint("mailbox_id","message_id"),)
    id:Mapped[int]=mapped_column(primary_key=True); mailbox_id:Mapped[int]=mapped_column(ForeignKey("mailboxes.id")); message_id:Mapped[str]=mapped_column(String(512)); conversation_id:Mapped[str|None]=mapped_column(String(512)); internet_message_id:Mapped[str|None]=mapped_column(String(998)); in_reply_to:Mapped[str|None]=mapped_column(String(998)); references:Mapped[str|None]=mapped_column(Text); thread_index:Mapped[str|None]=mapped_column(Text); sender:Mapped[str]=mapped_column(String(320)); receiver:Mapped[str]=mapped_column(String(320)); subject:Mapped[str]=mapped_column(Text); received_time:Mapped[datetime]=mapped_column(DateTime(timezone=True)); sent_time:Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); folder:Mapped[str]=mapped_column(String(80)); categories:Mapped[list]=mapped_column(JSON,default=list); classification:Mapped[Classification]=mapped_column(Enum(Classification)); status:Mapped[EmailStatus]=mapped_column(Enum(EmailStatus)); manually_ignored:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0"); read_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); replied_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); pending_hours:Mapped[float]=mapped_column(Float,default=0); sla_tier:Mapped[SLATier]=mapped_column(Enum(SLATier),default=SLATier.HEALTHY); assigned_employee_id:Mapped[int|None]=mapped_column(ForeignKey("employees.id")); mailbox=relationship("Mailbox"); employee=relationship("Employee")
    recipients=relationship("EmailRecipient",cascade="all, delete-orphan")


class EmailRecipient(Base):
    __tablename__="email_recipients"
    email_id:Mapped[int]=mapped_column(ForeignKey("emails.id",ondelete="CASCADE"),primary_key=True)
    employee_id:Mapped[int]=mapped_column(ForeignKey("employees.id",ondelete="CASCADE"),primary_key=True,index=True)
    employee=relationship("Employee")


class SLARule(Base):
    __tablename__="sla_rules"; id:Mapped[int]=mapped_column(primary_key=True); tier:Mapped[SLATier]=mapped_column(Enum(SLATier),unique=True); threshold_hours:Mapped[float]=mapped_column(Float); business_hours_only:Mapped[bool]=mapped_column(Boolean,default=True); notify_manager_at_hours:Mapped[float|None]=mapped_column(Float); notify_director_at_hours:Mapped[float|None]=mapped_column(Float)
class BusinessCalendar(Base):
    __tablename__="business_calendars"; id:Mapped[int]=mapped_column(primary_key=True); mailbox_id:Mapped[int|None]=mapped_column(ForeignKey("mailboxes.id")); timezone:Mapped[str]=mapped_column(String(64)); workday_start:Mapped[str]=mapped_column(String(5),default="09:00"); workday_end:Mapped[str]=mapped_column(String(5),default="18:00"); weekdays:Mapped[list]=mapped_column(JSON,default=lambda:[0,1,2,3,4]); holidays:Mapped[list]=mapped_column(JSON,default=list)
class ClassificationRule(Base):
    __tablename__="classification_rules"; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(120)); priority:Mapped[int]=mapped_column(Integer); field:Mapped[str]=mapped_column(String(30)); pattern:Mapped[str]=mapped_column(Text); classification:Mapped[Classification]=mapped_column(Enum(Classification)); active:Mapped[bool]=mapped_column(Boolean,default=True)
class EscalationEvent(Base):
    __tablename__="escalation_events"; __table_args__=(UniqueConstraint("email_id","threshold"),); id:Mapped[int]=mapped_column(primary_key=True); email_id:Mapped[int]=mapped_column(ForeignKey("emails.id")); threshold:Mapped[str]=mapped_column(String(40)); recipient_role:Mapped[str]=mapped_column(String(40)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class SyncLog(Base):
    __tablename__="sync_logs"; id:Mapped[int]=mapped_column(primary_key=True); mailbox_id:Mapped[int]=mapped_column(ForeignKey("mailboxes.id")); action:Mapped[str]=mapped_column(String(80)); api_response:Mapped[str|None]=mapped_column(Text); errors:Mapped[str|None]=mapped_column(Text); started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); finished_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); emails_fetched:Mapped[int]=mapped_column(Integer,default=0); emails_new:Mapped[int]=mapped_column(Integer,default=0); status:Mapped[str]=mapped_column(String(30))
class UIContent(Base):
    __tablename__="ui_content"; __table_args__=(UniqueConstraint("source_text_sha256", name="uq_ui_content_source_text_sha256"),)
    id:Mapped[int]=mapped_column(primary_key=True); source_text:Mapped[str]=mapped_column(Text); source_text_sha256:Mapped[str]=mapped_column(String(64),nullable=False); rendered_text:Mapped[str]=mapped_column(Text); active:Mapped[bool]=mapped_column(Boolean,default=True)

@event.listens_for(UIContent, "before_insert")
@event.listens_for(UIContent, "before_update")
def _hash_ui_content_source(mapper, connection, row):
    row.source_text_sha256 = hashlib.sha256(row.source_text.encode("utf-8")).hexdigest()
class AuthSession(Base):
    __tablename__="auth_sessions"; id:Mapped[str]=mapped_column(String(64),primary_key=True); family_id:Mapped[str]=mapped_column(String(64),index=True); user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True); refresh_jti_hash:Mapped[str]=mapped_column(String(64)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); last_used_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True); revoke_reason:Mapped[str|None]=mapped_column(String(80)); source_hash:Mapped[str|None]=mapped_column(String(64)); user_agent_hash:Mapped[str|None]=mapped_column(String(64))
class LoginThrottle(Base):
    __tablename__="login_throttles"; key_hash:Mapped[str]=mapped_column(String(64),primary_key=True); failures:Mapped[int]=mapped_column(Integer,default=0); window_started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); blocked_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class OAuthTransaction(Base):
    __tablename__="oauth_transactions"; id:Mapped[int]=mapped_column(primary_key=True); state_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True); provider:Mapped[str]=mapped_column(String(20)); user_id:Mapped[int]=mapped_column(ForeignKey("users.id")); auth_session_id:Mapped[str]=mapped_column(ForeignKey("auth_sessions.id")); mailbox_id:Mapped[int]=mapped_column(ForeignKey("mailboxes.id")); browser_hash:Mapped[str]=mapped_column(String(64)); payload_ciphertext:Mapped[str]=mapped_column(Text); payload_nonce:Mapped[str]=mapped_column(String(64)); key_id:Mapped[str]=mapped_column(String(64)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); consumed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
class ManagerMailboxAccess(Base):
    __tablename__="manager_mailbox_access"; __table_args__=(UniqueConstraint("user_id","mailbox_id"),); id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True); mailbox_id:Mapped[int]=mapped_column(ForeignKey("mailboxes.id"),index=True)
class AIReviewSetting(Base):
    __tablename__="ai_review_settings"; id:Mapped[int]=mapped_column(primary_key=True); enabled:Mapped[bool]=mapped_column(Boolean,default=False); approved_by:Mapped[int|None]=mapped_column(ForeignKey("users.id")); approved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class AIProviderSetting(Base):
    __tablename__="ai_provider_settings"; id:Mapped[int]=mapped_column(primary_key=True); provider:Mapped[str]=mapped_column(String(20)); model:Mapped[str]=mapped_column(String(120)); keys:Mapped[dict]=mapped_column(JSON,default=dict)
class ConversationAIReview(Base):
    __tablename__="conversation_ai_reviews"; __table_args__=(UniqueConstraint("mailbox_id","conversation_key","employee_id",name="uq_review_mailbox_conversation_employee"),)
    id:Mapped[int]=mapped_column(primary_key=True); mailbox_id:Mapped[int]=mapped_column(ForeignKey("mailboxes.id"),index=True); conversation_key:Mapped[str]=mapped_column(String(512)); employee_id:Mapped[int]=mapped_column(ForeignKey("employees.id"),index=True); received_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); last_message_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); status:Mapped[str]=mapped_column(String(20),default="pending"); analysis:Mapped[str|None]=mapped_column(Text); rubric:Mapped[dict|None]=mapped_column(JSON); error_code:Mapped[str|None]=mapped_column(String(80)); analyzed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class SecurityAuditEvent(Base):
    __tablename__="security_audit_events"; id:Mapped[int]=mapped_column(primary_key=True); actor_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),index=True); action:Mapped[str]=mapped_column(String(80),index=True); object_type:Mapped[str|None]=mapped_column(String(80)); object_id:Mapped[str|None]=mapped_column(String(128)); outcome:Mapped[str]=mapped_column(String(30),index=True); source_hash:Mapped[str|None]=mapped_column(String(64)); request_id:Mapped[str|None]=mapped_column(String(64),index=True); details:Mapped[dict]=mapped_column(JSON,default=dict); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
