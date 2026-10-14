from datetime import date,datetime,time
import regex
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import BaseModel, EmailStr, Field,field_validator,model_validator
from app.models.entities import Classification,MailboxStatus, Role,SLATier

class TokenResponse(BaseModel): access_token:str;token_type:str="bearer";expires_in:int
class MailboxCreate(BaseModel):
    address:EmailStr;display_name:str=Field(min_length=1,max_length=120);provider:Literal["microsoft","gmail"]="microsoft";timezone:str="Asia/Kolkata"
    azure_client_id:str|None=Field(default=None,max_length=128);azure_tenant_id:str|None=Field(default=None,max_length=128);azure_client_secret:str|None=Field(default=None,max_length=2048)
    @model_validator(mode="after")
    def azure_fields_together(self):
        fields=tuple(value.strip() if value else "" for value in (self.azure_client_id,self.azure_tenant_id,self.azure_client_secret))
        if any(fields) and (self.provider!="microsoft" or not all(fields)):
            raise ValueError("Microsoft mailbox requires Azure Client ID, Tenant ID, and Client Secret together")
        return self
class MailboxUpdate(BaseModel):
    display_name:str|None=None;status:MailboxStatus|None=None;timezone:str|None=None
    azure_client_id:str|None=Field(default=None,max_length=128);azure_tenant_id:str|None=Field(default=None,max_length=128);azure_client_secret:str|None=Field(default=None,max_length=2048)
class MailboxOut(BaseModel):
    id:int;address:str;display_name:str;provider:str;status:MailboxStatus;timezone:str;connected:bool=False;last_synced_at:datetime|None;last_sync_error:str|None
    azure_client_id:str|None=None;azure_tenant_id:str|None=None;azure_secret_saved:bool=False
    model_config={"from_attributes":True}
class GraphCheckInput(BaseModel): mailbox:EmailStr|None=None
class SyncSettingsInput(BaseModel):
    interval_seconds:int=Field(default=10,ge=10,le=86400)
    scheduler_enabled:bool=True
class GmailConfigInput(BaseModel):
    google_client_id:str=Field(min_length=1,max_length=256)
    google_client_secret:str=Field(min_length=1,max_length=512)
class SLARuleInput(BaseModel): tier:SLATier;threshold_hours:float=Field(ge=0);business_hours_only:bool=True;notify_manager_at_hours:float|None=Field(default=None,ge=0);notify_director_at_hours:float|None=Field(default=None,ge=0)
class ClassificationRuleInput(BaseModel):
    name:str=Field(min_length=1,max_length=120);priority:int;field:Literal["sender","subject","domain"];pattern:str=Field(min_length=1,max_length=512);classification:Classification;active:bool=True
    @field_validator("pattern")
    @classmethod
    def valid_regex(cls,value:str):
        try:regex.compile(value)
        except regex.error as exc:raise ValueError(f"Invalid regular expression: {exc}") from exc
        return value
class EmployeeInput(BaseModel): name:str=Field(min_length=1,max_length=120);email:EmailStr;department:str=Field(default="General",min_length=1,max_length=120);active:bool=True
class EmployeeUpdate(BaseModel): name:str|None=Field(default=None,min_length=1,max_length=120);email:EmailStr|None=None;department:str=Field(default="General",min_length=1,max_length=120);active:bool|None=None
class CalendarInput(BaseModel):
    mailbox_id:int|None=None;timezone:str="Asia/Kolkata";workday_start:str="09:00";workday_end:str="18:00";weekdays:list[int]=Field(default_factory=lambda:[0,1,2,3,4]);holidays:list[str]=Field(default_factory=list)
    @model_validator(mode="after")
    def valid_calendar(self):
        try:ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:raise ValueError("Unknown IANA timezone") from exc
        try:start=time.fromisoformat(self.workday_start);end=time.fromisoformat(self.workday_end)
        except ValueError as exc:raise ValueError("Working hours must use HH:MM format") from exc
        if start>=end:raise ValueError("workday_end must be later than workday_start")
        if not self.weekdays or any(day not in range(7) for day in self.weekdays):raise ValueError("weekdays must contain values from 0 to 6")
        try:[date.fromisoformat(value) for value in self.holidays]
        except ValueError as exc:raise ValueError("holidays must use YYYY-MM-DD format") from exc
        return self
def _strong_password(value:str)->str:
    if value.lower() in {"passwordpassword","replace-before-first-start","oeis-admin@july2026#47"}:raise ValueError("Password is too common or is a known development password")
    return value
class UserInput(BaseModel):
    email:EmailStr;name:str=Field(min_length=1,max_length=120);password:str=Field(min_length=15,max_length=128);role:Role;active:bool=True
    _password_policy=field_validator("password")(_strong_password)
class UserUpdate(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=120);password:str|None=Field(default=None,min_length=15,max_length=128);role:Role|None=None;active:bool|None=None
    _password_policy=field_validator("password")(_strong_password)
class ManagerMailboxAccessInput(BaseModel):mailbox_ids:list[int]=Field(default_factory=list,max_length=500)
class ReplyInput(BaseModel):body:str=Field(min_length=1,max_length=10000)
class WritingAssistantInput(BaseModel):
    body:str=Field(default="",max_length=10000);mode:Literal["draft","correct","rewrite"]="draft"
    @model_validator(mode="after")
    def require_draft_for_edits(self):
        if self.mode!="draft" and not self.body.strip():raise ValueError("A draft is required for correction or rewrite")
        return self
def _safe_ui_text(value:str|None):
    if value is None:return value
    if regex.search(r"(?i)<\s*script\b|\bon[a-z]+\s*=|javascript\s*:",value):raise ValueError("Active HTML content is not allowed")
    return value
class UIContentInput(BaseModel):
    source:str=Field(min_length=1,max_length=500,pattern=r"^[A-Za-z0-9._-]+$");text:str=Field(min_length=0,max_length=10000);active:bool=True
    _safe_text=field_validator("text")(_safe_ui_text)
class UIContentUpdate(BaseModel):
    text:str|None=Field(default=None,max_length=10000);active:bool|None=None
    _safe_text=field_validator("text")(_safe_ui_text)
