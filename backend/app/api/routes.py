from datetime import date,datetime,time as dt_time,timedelta,timezone
import asyncio
import csv
import hashlib
from email.utils import parseaddr
import os
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException,Query,Request,Response,status
from fastapi.responses import HTMLResponse,StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
import httpx
from sqlalchemy import delete,func,or_,select
from sqlalchemy.orm import Session,joinedload,selectinload
from app.core.database import SessionLocal,get_db
from app.core.config import BACKEND_ENV,get_settings
from app.core.security import consume_dummy_password_check,decode_token,issue_session,require_roles,revoke_user_sessions,rotate_session,verify_and_upgrade_password
from app.models.entities import AIReviewSetting,AuthSession,BusinessCalendar,Classification,ClassificationRule,ConversationAIReview,Email,EmailRecipient,EmailStatus,Employee,EscalationEvent,Mailbox,MailboxStatus,ManagerMailboxAccess,Role,SecurityAuditEvent,SLARule,SLATier,SyncLog,UIContent,User
from app.repositories.dashboard import DashboardRepository
from app.repositories.email import EmailRepository,employee_mail_scope
from app.services.employees import is_company_employee_email
from app.schemas.api import CalendarInput,ClassificationRuleInput,EmployeeInput,EmployeeUpdate,GmailConfigInput,GraphCheckInput,MailboxCreate,MailboxOut,MailboxUpdate,ManagerMailboxAccessInput,ReplyInput,SLARuleInput,SyncSettingsInput,TokenResponse,UIContentInput,UIContentUpdate,UserInput,UserUpdate,WritingAssistantInput
from app.services.graph import DelegatedGraphDeltaSync,GraphDeltaSync,delegated_auth_code_scopes,delegated_authority_tenant,delegated_graph_application,delegated_scopes
from app.services.gmail import GmailDeltaSync,gmail_scopes
from app.services.content import content as ui_text,seed_ui_content
from app.core.security import hash_password
from app.services.security_events import audit,check_login_allowed,clear_login_failures,record_login_failure,validate_cookie_origin
from app.services.secrets import get_mailbox_token,set_mailbox_token,set_mailbox_azure_secret,mailbox_graph_settings
from app.services.oauth_transactions import _digest,clear_oauth_cookie,consume_transaction,new_oauth_values,pkce_pair,save_transaction
from app.services.authorization import mailbox_scope,require_email_scope
from app.services.writing_assistant import WritingAssistantError,suggest_reply
from app.services.ai_provider import active_ai_settings,provider_status,save_ai_settings
from app.services.conversation_reviews import REVIEW_VERSION,_review_activity,_thread_rows
from app.services.notifications import report_mailbox_available
from app.services.sla import Calendar,elapsed_hours,tier_for
from app.services.scheduler import apply_sync_settings,build_scheduler
from io import BytesIO,StringIO
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph,SimpleDocTemplate,Spacer
from html import escape

router=APIRouter(prefix="/api");viewer=Depends(require_roles(Role.ADMIN,Role.MANAGER));admin=Depends(require_roles(Role.ADMIN))
def _utc_timestamp(value:datetime|None)->datetime|None:
    if value is None:return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
def _report_conversation_key(email:Email)->str:return email.conversation_id or f"message:{hashlib.sha256(email.message_id.encode()).hexdigest()}"
def _report_cutoff(period:str)->datetime:
    now=datetime.now(ZoneInfo(get_settings().app_timezone))
    cutoff=now.replace(hour=0,minute=0,second=0,microsecond=0) if period=="daily" else now-timedelta(days=7) if period=="weekly" else now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    return cutoff.astimezone(timezone.utc)
def _work_handling_score(emails:list[Email],warning_hours:float|None,rubrics:list[dict]|None=None,quality_threads:int=0)->dict:
    actionable=[email for email in emails if email.status in {EmailStatus.PENDING,EmailStatus.REPLIED}]
    if not actionable:return {"score":None,"factors":[],"sample_size":0}
    replied=[email for email in actionable if email.status==EmailStatus.REPLIED]
    factors=[
        {"label":"Reply completed","value":round(100*len(replied)/len(actionable)),"weight":10,"detail":f"{len(replied)} of {len(actionable)} customer mails replied"},
    ]
    if replied:
        timely=sum(email.pending_hours is not None and email.pending_hours<=1 for email in replied)
        speed=round(100*timely/len(replied)); speed_detail=f"{timely} of {len(replied)} replies within the 1h coaching target"
    else:
        speed=None; speed_detail="No replied mail available"
    factors.append({"label":"Reply speed","value":speed,"weight":10,"detail":speed_detail})
    for key,label,weight in (("professionalism","Professional answer",30),("detail","Answer detail",20),("clarity","Clear language",10),("ownership","Ownership and follow-through",10),("actionability","Actionable next step",10)):
        values=[rubric.get(key,{}).get("score") for rubric in (rubrics or [])]
        available=quality_threads>0 and len(values)==quality_threads and all(type(value) is int and 0<=value<=100 for value in values)
        factors.append({"label":label,"value":round(sum(values)/len(values)) if available else None,"weight":weight,"detail":f"Based on {quality_threads} reviewed conversation{'s' if quality_threads!=1 else ''}" if available else "Employee reply evidence not available for every conversation"})
    assessed=sum(factor["weight"] for factor in factors if factor["value"] is not None)
    points=round(sum(factor["value"]*factor["weight"]/100 for factor in factors if factor["value"] is not None),1)
    return {"score":round(points) if assessed==100 else None,"earned_points":points,"assessed_points":assessed,"factors":factors,"sample_size":len(actionable)}
def _write_env_values(path:Path,values:dict[str,str])->None:
    existing=path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending=dict(values)
    rows:list[str]=[]
    for line in existing:
        key,sep,_=line.partition("=")
        if sep and key in pending:
            rows.append(f"{key}={pending.pop(key)}")
        else:
            rows.append(line)
    rows.extend(f"{key}={value}" for key,value in pending.items())
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("\n".join(rows).rstrip()+"\n",encoding="utf-8")
def _oauth_error(db:Session,key:str,status_code:int=400,detail:str|None=None,body_key:str='oauth.expired.body')->HTMLResponse:
    body=ui_text(db,body_key)
    if detail:body=f"{body}<br><small>Microsoft: {escape(detail[:300])}</small>"
    response=HTMLResponse(f"<h2>{escape(ui_text(db,key))}</h2><p>{body}</p>",status_code=status_code);clear_oauth_cookie(response);return response
def _oauth_error_detail(db:Session,title_key:str,body_key:str,status_code:int=400)->HTMLResponse:
    response=HTMLResponse(f"<h2>{escape(ui_text(db,title_key))}</h2><p>{escape(ui_text(db,body_key))}</p>",status_code=status_code);clear_oauth_cookie(response);return response
@router.get("/health")
def health():return {"status":"healthy","time":datetime.now(timezone.utc)}
@router.get("/ui-content")
def ui_content(db:Session=Depends(get_db)):
    seed_ui_content(db)
    rows=db.scalars(select(UIContent).where(UIContent.active.is_(True))).all()
    return {"items":[{"source":row.source_text,"text":row.rendered_text} for row in rows]}
@router.get("/ui-content/manage",dependencies=[admin])
def manage_ui_content(db:Session=Depends(get_db)):
    seed_ui_content(db)
    rows=db.scalars(select(UIContent).order_by(UIContent.source_text)).all()
    return [{"id":row.id,"source":row.source_text,"text":row.rendered_text,"active":row.active} for row in rows]
@router.post("/ui-content/manage",dependencies=[admin],status_code=201)
def create_ui_content(payload:UIContentInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    if db.scalar(select(UIContent).where(UIContent.source_text==payload.source)):raise HTTPException(409,ui_text(db,"api.error.content_exists"))
    row=UIContent(source_text=payload.source,rendered_text=payload.text,active=payload.active);db.add(row);db.flush();audit(db,request,"ui_content.create","success",principal["user_id"],"ui_content",row.id);db.commit();db.refresh(row);return {"id":row.id,"source":row.source_text,"text":row.rendered_text,"active":row.active}
@router.patch("/ui-content/manage/{content_id}",dependencies=[admin])
def update_ui_content(content_id:int,payload:UIContentUpdate,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(UIContent,content_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.content_missing"))
    values=payload.model_dump(exclude_unset=True)
    if "text" in values:row.rendered_text=values["text"]
    if "active" in values:row.active=values["active"]
    audit(db,request,"ui_content.update","success",principal["user_id"],"ui_content",row.id);db.commit();db.refresh(row);return {"id":row.id,"source":row.source_text,"text":row.rendered_text,"active":row.active}
@router.delete("/ui-content/manage/{content_id}",dependencies=[admin],status_code=204)
def delete_ui_content(content_id:int,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(UIContent,content_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.content_missing"))
    db.delete(row);audit(db,request,"ui_content.delete","success",principal["user_id"],"ui_content",content_id);db.commit();return None
def _refresh_cookie_name()->str:return "__Host-oeis_refresh" if get_settings().production else "oeis_refresh"
def _set_refresh_cookie(response:Response,token:str)->None:
    settings=get_settings();response.set_cookie(_refresh_cookie_name(),token,max_age=settings.refresh_token_days*86400,httponly=True,secure=settings.production,samesite="strict",path="/")
def _clear_refresh_cookie(response:Response)->None:response.delete_cookie(_refresh_cookie_name(),httponly=True,secure=get_settings().production,samesite="strict",path="/")
@router.post("/auth/login",response_model=TokenResponse)
def login(request:Request,response:Response,form:OAuth2PasswordRequestForm=Depends(),db:Session=Depends(get_db)):
    validate_cookie_origin(request)
    try:check_login_allowed(db,form.username,request)
    except HTTPException:
        audit(db,request,"auth.login","blocked",details={"reason":"rate_limit"});db.commit();raise
    user=db.scalar(select(User).where(User.email==form.username,User.active.is_(True)))
    valid,upgraded=verify_and_upgrade_password(form.password,user.password_hash) if user else (consume_dummy_password_check(form.password) or False,None)
    if not user or not valid:
        record_login_failure(db,form.username,request);audit(db,request,"auth.login","denied",details={"reason":"invalid_credentials"});db.commit();raise HTTPException(status_code=401,detail=ui_text(db,"api.error.invalid_credentials"))
    if upgraded:user.password_hash=upgraded
    clear_login_failures(db,form.username,request);access,refresh_token,session=issue_session(db,user,request);audit(db,request,"auth.login","success",user.id,"auth_session",session.id);db.commit();_set_refresh_cookie(response,refresh_token)
    return TokenResponse(access_token=access,expires_in=get_settings().access_token_minutes*60)
@router.post("/auth/refresh",response_model=TokenResponse)
def refresh(request:Request,response:Response,db:Session=Depends(get_db)):
    validate_cookie_origin(request);token=request.cookies.get(_refresh_cookie_name())
    if not token:raise HTTPException(status_code=401,detail=ui_text(db,"api.error.invalid_credentials"))
    try:access,refresh_token,user,session=rotate_session(db,token)
    except HTTPException:
        audit(db,request,"auth.refresh","denied",details={"reason":"invalid_or_replayed"});db.commit();_clear_refresh_cookie(response);raise
    audit(db,request,"auth.refresh","success",user.id,"auth_session",session.id);db.commit();_set_refresh_cookie(response,refresh_token)
    return TokenResponse(access_token=access,expires_in=get_settings().access_token_minutes*60)
@router.post("/auth/logout",status_code=204)
def logout(request:Request,response:Response,db:Session=Depends(get_db)):
    validate_cookie_origin(request);token=request.cookies.get(_refresh_cookie_name());actor=None
    if token:
        try:
            payload=decode_token(token,"refresh");session=db.get(AuthSession,payload["sid"])
            if session and not session.revoked_at:session.revoked_at=datetime.now(timezone.utc);session.revoke_reason="logout";actor=session.user_id
        except HTTPException:pass
    audit(db,request,"auth.logout","success",actor);db.commit();_clear_refresh_cookie(response);return None
@router.get("/users",dependencies=[admin])
def users(db:Session=Depends(get_db)):
    access={user_id:list(db.scalars(select(ManagerMailboxAccess.mailbox_id).where(ManagerMailboxAccess.user_id==user_id))) for user_id in db.scalars(select(User.id))}
    return [{"id":x.id,"email":x.email,"name":x.name,"role":x.role,"active":x.active,"mailbox_ids":access[x.id]} for x in db.scalars(select(User).order_by(User.name))]
@router.post("/users",dependencies=[admin],status_code=201)
def create_user(payload:UserInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    if db.scalar(select(User).where(User.email==payload.email)):raise HTTPException(409,ui_text(db,"api.error.user_exists"))
    row=User(email=payload.email,name=payload.name,password_hash=hash_password(payload.password),role=payload.role,active=payload.active);db.add(row);db.flush();audit(db,request,"user.create","success",principal["user_id"],"user",row.id,{"role":row.role.value,"active":row.active});db.commit();db.refresh(row);return {"id":row.id,"email":row.email,"name":row.name,"role":row.role,"active":row.active}
@router.patch("/users/{user_id}",dependencies=[admin])
def update_user(user_id:int,payload:UserUpdate,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(User,user_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.user_missing"))
    values=payload.model_dump(exclude_unset=True);password=values.pop("password",None)
    if "email" in values and values["email"] is None:
        raise HTTPException(422,"Email is required")
    if "email" in values and values["email"]!=row.email and db.scalar(select(User.id).where(func.lower(User.email)==values["email"].lower(),User.id!=row.id)):
        raise HTTPException(409,ui_text(db,"api.error.user_exists"))
    email_changed="email" in values and values["email"]!=row.email
    if row.role==Role.ADMIN and row.active and (values.get("active") is False or values.get("role")==Role.MANAGER):
        active_admins=db.scalar(select(func.count()).select_from(User).where(User.role==Role.ADMIN,User.active.is_(True))) or 0
        if active_admins<=1:raise HTTPException(409,"The last active Admin cannot be disabled or demoted")
    for key,value in values.items():setattr(row,key,value)
    if password:row.password_hash=hash_password(password)
    if row.role==Role.ADMIN:db.execute(delete(ManagerMailboxAccess).where(ManagerMailboxAccess.user_id==row.id))
    security_changed=bool(password) or email_changed or "active" in values or "role" in values
    if security_changed:revoke_user_sessions(db,row.id,"user_security_change")
    audit(db,request,"user.update","success",principal["user_id"],"user",row.id,{"password_changed":bool(password),"email_changed":email_changed,"role":row.role.value,"active":row.active});db.commit();db.refresh(row);return {"id":row.id,"email":row.email,"name":row.name,"role":row.role,"active":row.active,"reauthenticate":row.id==principal["user_id"] and security_changed}
@router.put("/users/{user_id}/mailbox-access",dependencies=[admin])
def update_manager_mailbox_access(user_id:int,payload:ManagerMailboxAccessInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    user=db.get(User,user_id)
    if not user or user.role!=Role.MANAGER:raise HTTPException(404,"Manager not found")
    mailbox_ids=sorted(set(payload.mailbox_ids));existing=set(db.scalars(select(Mailbox.id).where(Mailbox.id.in_(mailbox_ids))))
    if existing!=set(mailbox_ids):raise HTTPException(422,"One or more mailbox IDs are invalid")
    db.execute(delete(ManagerMailboxAccess).where(ManagerMailboxAccess.user_id==user_id));db.add_all([ManagerMailboxAccess(user_id=user_id,mailbox_id=mailbox_id) for mailbox_id in mailbox_ids]);audit(db,request,"manager.mailbox_access.update","success",principal["user_id"],"user",user_id,{"mailbox_count":len(mailbox_ids)});db.commit();return {"user_id":user_id,"mailbox_ids":mailbox_ids}
@router.get("/dashboard/kpis",dependencies=[viewer])
def dashboard_kpis(principal:dict=viewer,db:Session=Depends(get_db)):return DashboardRepository(db).kpis(mailbox_scope(db,principal))
@router.get("/system/readiness",dependencies=[viewer])
def system_readiness(principal:dict=viewer,db:Session=Depends(get_db)):
    settings=get_settings();allowed=mailbox_scope(db,principal);scope=[] if allowed is None else [Mailbox.id.in_(allowed)];active=list(db.scalars(select(Mailbox).where(Mailbox.status!=MailboxStatus.PAUSED,*scope)));configured_count=len(active);healthy=db.scalar(select(func.count()).select_from(Mailbox).where(Mailbox.status==MailboxStatus.ACTIVE,*scope)) or 0;errors=db.scalar(select(func.count()).select_from(Mailbox).where(Mailbox.status==MailboxStatus.ERROR,*scope)) or 0;paused=db.scalar(select(func.count()).select_from(Mailbox).where(Mailbox.status==MailboxStatus.PAUSED,*scope)) or 0;last_sync=db.scalar(select(func.max(Mailbox.last_synced_at)).where(*scope));warnings=sum(1 for row in active if row.last_sync_error and row.last_sync_error.startswith("Temporary sync issue:"))
    graph_configured=any(row.provider=="microsoft" and bool((configured:=mailbox_graph_settings(row,settings)).azure_client_id and (row.connected or configured.azure_tenant_id and (configured.azure_client_secret or configured.azure_client_certificate_path))) for row in active);gmail_configured=bool(settings.google_client_id and settings.google_client_secret)
    integration_configured=bool(active) and all((row.connected and gmail_configured) if row.provider=="gmail" else bool((configured:=mailbox_graph_settings(row,settings)).azure_client_id and (row.connected or configured.azure_tenant_id and (configured.azure_client_secret or configured.azure_client_certificate_path))) for row in active)
    return {"operational":bool(integration_configured and configured_count and not errors and last_sync),"integration_configured":integration_configured,"graph_configured":graph_configured,"gmail_configured":gmail_configured,"smtp_configured":bool(settings.smtp_host and settings.smtp_username and settings.smtp_password) or report_mailbox_available(),"configured_mailboxes":configured_count,"healthy_mailboxes":healthy,"error_mailboxes":errors,"warning_mailboxes":warnings,"paused_mailboxes":paused,"last_successful_sync":last_sync}
@router.get("/system/graph-setup",dependencies=[admin])
def graph_setup(mailbox:str|None=None,db:Session=Depends(get_db)):
    row=db.scalar(select(Mailbox).where(Mailbox.address==mailbox)) if mailbox else None
    settings=mailbox_graph_settings(row,get_settings()) if row else get_settings();using_secret=bool(settings.azure_client_secret);using_certificate=bool(settings.azure_client_certificate_path);graph_configured=bool(settings.azure_tenant_id and settings.azure_client_id and (using_secret or using_certificate))
    missing=[name for name,value in {"AZURE_CLIENT_ID":settings.azure_client_id,"AZURE_TENANT_ID":settings.azure_tenant_id,"AZURE_CLIENT_SECRET or AZURE_CLIENT_CERTIFICATE_PATH":using_secret or using_certificate}.items() if not value]
    app_id=settings.azure_client_id or "<AZURE_CLIENT_ID>";tenant=settings.azure_tenant_id or "common";address=mailbox or "<MAILBOX_ADDRESS>";group=ui_text(db,"graph.group.allowed_mailboxes")
    azure_cli=[
        ui_text(db,"graph.script.requires_azure_cli"),
        "az login --tenant <AZURE_TENANT_ID>",
        f'APP_ID=$(az ad app create --display-name "{ui_text(db,"graph.script.app_display_name")}" --sign-in-audience AzureADMyOrg --query appId -o tsv)',
        "az ad sp create --id $APP_ID",
        'GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"',
        'MAIL_READ_ROLE_ID="810c84a8-4a9e-49e6-bf7d-12d183f40d01"',
        'MAIL_SEND_ROLE_ID="b633e1c5-b582-4048-a93e-9f11b44c7e96"',
        "az ad app permission add --id $APP_ID --api $GRAPH_APP_ID --api-permissions ${MAIL_READ_ROLE_ID}=Role ${MAIL_SEND_ROLE_ID}=Role",
        "az ad app permission admin-consent --id $APP_ID",
        f'CLIENT_SECRET=$(az ad app credential reset --id $APP_ID --display-name "{ui_text(db,"graph.script.secret_display_name")}" --years 1 --query password -o tsv)',
        'TENANT_ID=$(az account show --query tenantId -o tsv)',
        'printf "AZURE_TENANT_ID=%s\\nAZURE_CLIENT_ID=%s\\nAZURE_CLIENT_SECRET=%s\\nGRAPH_SCOPE=https://graph.microsoft.com/.default\\n" "$TENANT_ID" "$APP_ID" "$CLIENT_SECRET"',
    ]
    commands=[
        "Connect-ExchangeOnline",
        f'New-DistributionGroup -Name "{group}" -Type Security',
        f'Add-DistributionGroupMember -Identity "{group}" -Member {address}',
        f'New-ApplicationAccessPolicy -AppId {app_id} -PolicyScopeGroupId "{group}" -AccessRight RestrictAccess -Description "{ui_text(db,"graph.exchange.description")}"',
        f"Test-ApplicationAccessPolicy -Identity {address} -AppId {app_id}",
        f"Test-ApplicationAccessPolicy -Identity unauthorized@example.com -AppId {app_id}",
    ]
    env_template=[
        f"AZURE_TENANT_ID={settings.azure_tenant_id or '<OPTIONAL_FOR_PERSONAL_OUTLOOK_OR_COMMON>'}",
        f"AZURE_CLIENT_ID={app_id}",
        "AZURE_CLIENT_SECRET=<CLIENT_SECRET_VALUE>",
        "GRAPH_SCOPE=https://graph.microsoft.com/.default",
    ]
    admin_consent_url=f"https://login.microsoftonline.com/{tenant}/adminconsent?client_id={app_id}" if settings.azure_tenant_id and settings.azure_client_id else None
    return {"graph_configured":graph_configured,"missing":missing,"credential_status":{"tenant_id_saved":bool(settings.azure_tenant_id),"client_id_saved":bool(settings.azure_client_id),"client_secret_saved":bool(settings.azure_client_secret),"runtime_loaded":bool(settings.azure_client_id and settings.azure_client_secret)},"required_permission":ui_text(db,"graph.permission.required"),"delegated_setup":{"redirect_uri":settings.graph_redirect_uri,"scopes":" ".join(delegated_auth_code_scopes(settings)),"supported_accounts":ui_text(db,"graph.setup.accounts"),"oauth_configured":bool(settings.azure_client_id and settings.azure_client_secret)},"portal_links":{"app_registration":"https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade/quickStartType~/null/isMSAApp~/false","app_registrations":"https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade","api_permissions":"https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps","exchange_admin":"https://admin.exchange.microsoft.com/#/groups","admin_consent":admin_consent_url},"env_template":"\n".join(env_template),"azure_cli_commands":"\n".join(azure_cli),"exchange_policy_commands":"\n".join(commands)}
@router.post("/system/graph-check",dependencies=[admin])
async def check_graph(payload:GraphCheckInput):
    settings=get_settings()
    with SessionLocal() as db:
        graph_missing=ui_text(db,"api.error.graph_credentials_missing");graph_app_missing=ui_text(db,"api.error.graph_app_credentials_missing")
    if not settings.azure_client_id:raise HTTPException(503,graph_missing)
    try:
        mailbox_checked=False
        if payload.mailbox:
            with SessionLocal() as db:
                row=db.scalar(select(Mailbox).where(Mailbox.address==str(payload.mailbox)))
                if row:settings=mailbox_graph_settings(row,settings)
            if row and row.connected:
                graph=DelegatedGraphDeltaSync(settings,get_mailbox_token(row,settings),delegated_authority_tenant(row.address,settings))
                await graph.sync_mailbox(str(payload.mailbox));mailbox_checked=True
                return {"ok":True,"mailbox_checked":mailbox_checked}
        if not settings.azure_tenant_id or not (settings.azure_client_secret or settings.azure_client_certificate_path):raise HTTPException(503,graph_app_missing)
        graph=GraphDeltaSync(settings);await graph._token(True)
        if payload.mailbox:
            await graph.sync_mailbox(payload.mailbox);mailbox_checked=True
        return {"ok":True,"mailbox_checked":mailbox_checked}
    except HTTPException:raise
    except Exception as exc:
        with SessionLocal() as db:message=ui_text(db,"api.error.graph_check_failed",error=f"{type(exc).__name__}: connection failed")
        raise HTTPException(502,message) from exc
@router.get("/system/gmail-setup",dependencies=[admin])
def gmail_setup(db:Session=Depends(get_db)):
    settings=get_settings();configured=bool(settings.google_client_id and settings.google_client_secret)
    missing=[name for name,value in {"GOOGLE_CLIENT_ID":settings.google_client_id,"GOOGLE_CLIENT_SECRET":settings.google_client_secret}.items() if not value]
    scopes=" ".join(gmail_scopes(settings))
    return {"gmail_configured":configured,"missing":missing,"required_permission":ui_text(db,"gmail.permission.required"),"redirect_uri":settings.google_redirect_uri,"scopes":scopes,"portal_links":{"project":"https://console.cloud.google.com/projectcreate","api_library":"https://console.cloud.google.com/apis/library/gmail.googleapis.com","consent_screen":"https://console.cloud.google.com/auth/overview","credentials":"https://console.cloud.google.com/apis/credentials"},"env_template":"\n".join([f"GOOGLE_CLIENT_ID={settings.google_client_id or '<GOOGLE_CLIENT_ID>'}","GOOGLE_CLIENT_SECRET=<GOOGLE_CLIENT_SECRET>",f"GOOGLE_REDIRECT_URI={settings.google_redirect_uri}",f"GMAIL_SCOPES={scopes}"])}
@router.post("/system/gmail-setup",dependencies=[admin])
@router.patch("/system/gmail-setup",dependencies=[admin])
def update_gmail_setup(payload:GmailConfigInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    try:
        _write_env_values(BACKEND_ENV,{"GOOGLE_CLIENT_ID":payload.google_client_id.strip(),"GOOGLE_CLIENT_SECRET":payload.google_client_secret})
    except OSError as exc:
        raise HTTPException(503,"Backend environment is read-only. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the deployment environment.") from exc
    os.environ["GOOGLE_CLIENT_ID"]=payload.google_client_id.strip();os.environ["GOOGLE_CLIENT_SECRET"]=payload.google_client_secret
    get_settings.cache_clear()
    audit(db,request,"settings.gmail_credentials.update","success",principal["user_id"],details={"client_id_saved":True,"client_secret_saved":True});db.commit()
    return {"gmail_configured":True,"client_id_saved":True,"client_secret_saved":True}
@router.post("/system/gmail-check",dependencies=[admin])
async def check_gmail(payload:GraphCheckInput,db:Session=Depends(get_db)):
    settings=get_settings()
    if not settings.google_client_id or not settings.google_client_secret:raise HTTPException(503,ui_text(db,"api.error.gmail_credentials_missing"))
    if not payload.mailbox:raise HTTPException(422,ui_text(db,"api.error.gmail_mailbox_required"))
    row=db.scalar(select(Mailbox).where(Mailbox.address==str(payload.mailbox),Mailbox.provider=="gmail"))
    if not row or not row.connected:raise HTTPException(409,ui_text(db,"api.error.gmail_not_connected"))
    try:
        profile=await GmailDeltaSync(settings,get_mailbox_token(row,settings)).profile()
        if profile.get("emailAddress","").lower()!=row.address.lower():raise RuntimeError(ui_text(db,"api.error.gmail_account_mismatch"))
        return {"ok":True,"mailbox_checked":True,"email":profile.get("emailAddress")}
    except Exception as exc:
        raise HTTPException(502,ui_text(db,"api.error.gmail_check_failed",error=f"{type(exc).__name__}: connection failed")) from exc
@router.get("/emails/pending",dependencies=[viewer])
def pending(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),status_filter:str|None=Query(None,alias="status"),mailbox:int|None=None,employee:int|None=None,search:str|None=None,date_filter:str|None=None,principal:dict=viewer,db:Session=Depends(get_db)):
    rows,total=EmailRepository(db).pending(page,page_size,status_filter,mailbox,employee,search,date_filter,mailbox_scope(db,principal))
    return {"items":[{"serial_number":(page-1)*page_size+i,"id":e.id,"customer":e.sender,"email":e.sender,"from":e.sender,"to":e.receiver,"subject":e.subject,"mailbox":e.mailbox.address,"mailbox_timezone":e.mailbox.timezone,"received":_utc_timestamp(e.received_time),"read_at":_utc_timestamp(e.read_at),"pending_since":_utc_timestamp(e.received_time),"replied_at":_utc_timestamp(e.replied_at),"hours":e.pending_hours,"assigned_employee":", ".join(recipient.employee.name for recipient in e.recipients) if e.status==EmailStatus.PENDING and e.recipients else e.employee.name if e.employee else None,"replied_by":e.employee.name if e.status==EmailStatus.REPLIED and e.employee else None,"reply_outcome":("Replied by you" if e.assigned_employee_id==employee else "Not replied by you") if employee and e.status==EmailStatus.REPLIED else None,"priority":e.sla_tier.value,"status":e.status.value} for i,e in enumerate(rows,1)],"page":page,"page_size":page_size,"total":total}
@router.get("/emails/{email_id}",dependencies=[viewer])
def email_detail(email_id:int,principal:dict=viewer,db:Session=Depends(get_db)):
    row=require_email_scope(db,principal,db.get(Email,email_id))
    return {"id":row.id,"message_id":row.message_id,"conversation_id":row.conversation_id,"internet_message_id":row.internet_message_id,"sender":row.sender,"receiver":row.receiver,"subject":row.subject,"received_time":_utc_timestamp(row.received_time),"sent_time":_utc_timestamp(row.sent_time),"mailbox_timezone":row.mailbox.timezone,"folder":row.folder,"categories":row.categories,"classification":row.classification,"status":row.status,"read_at":_utc_timestamp(row.read_at),"replied_at":_utc_timestamp(row.replied_at),"pending_hours":row.pending_hours,"sla_tier":row.sla_tier,"assigned_employee_id":row.assigned_employee_id}
@router.patch("/emails/{email_id}/read",dependencies=[admin])
def mark_email_read(email_id:int,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=require_email_scope(db,principal,db.get(Email,email_id))
    if row.read_at is None: row.read_at=datetime.now(timezone.utc)
    audit(db,request,"email.read","success",principal["user_id"],"email",email_id);db.commit()
    return {"id":row.id,"read_at":_utc_timestamp(row.read_at)}
def _email_strategy(row:Email,settings):
    refresh_token=get_mailbox_token(row.mailbox,settings)
    if row.mailbox.provider=="gmail":
        if not refresh_token:raise RuntimeError("Gmail mailbox is not connected")
        return GmailDeltaSync(settings,refresh_token),refresh_token
    settings=mailbox_graph_settings(row.mailbox,settings)
    strategy=DelegatedGraphDeltaSync(settings,refresh_token,delegated_authority_tenant(row.mailbox.address,settings)) if refresh_token else GraphDeltaSync(settings)
    return strategy,refresh_token
def _save_refreshed_mailbox_token(row:Email,strategy,refresh_token:str|None,settings)->None:
    if row.mailbox.provider=="microsoft" and refresh_token and strategy.latest_refresh_token!=refresh_token:
        set_mailbox_token(row.mailbox,strategy.latest_refresh_token,settings)
@router.get("/emails/{email_id}/content",dependencies=[admin])
async def email_content(email_id:int,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=require_email_scope(db,principal,db.get(Email,email_id));settings=get_settings()
    try:
        strategy,refresh_token=_email_strategy(row,settings)
        content=await strategy.message_content(row.mailbox.address,row.message_id)
        _save_refreshed_mailbox_token(row,strategy,refresh_token,settings)
    except Exception as exc:
        audit(db,request,"email.content.read","failed",principal["user_id"],"email",email_id,{"provider":row.mailbox.provider,"reason":type(exc).__name__});db.commit()
        raise HTTPException(502,"Email content could not be loaded from the mail provider") from exc
    audit(db,request,"email.content.read","success",principal["user_id"],"email",email_id,{"provider":row.mailbox.provider});db.commit()
    return {"content":content,"content_type":"text/plain"}
@router.post("/emails/{email_id}/rewrite",dependencies=[admin])
async def rewrite_email_reply(email_id:int,payload:WritingAssistantInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=require_email_scope(db,principal,db.get(Email,email_id));settings=active_ai_settings(db,get_settings())
    if not settings.ai_api_key:raise HTTPException(503,"AI writing assistance is not configured")
    try:
        strategy,refresh_token=_email_strategy(row,settings)
        incoming=await strategy.message_content(row.mailbox.address,row.message_id)
        result=await suggest_reply(settings,row.sender,row.subject,incoming,payload.body,payload.mode)
        _save_refreshed_mailbox_token(row,strategy,refresh_token,settings)
    except WritingAssistantError as exc:
        audit(db,request,"email.reply.assist","failed",principal["user_id"],"email",email_id,{"mode":payload.mode,"reason":"ai_service"});db.commit()
        if exc.status_code in {402,429}:raise HTTPException(429,"AI provider limit reached. Open AI Settings and choose another provider or model.") from exc
        raise HTTPException(502,"AI could not prepare a reply. Please edit the draft manually.") from exc
    except Exception as exc:
        audit(db,request,"email.reply.assist","failed",principal["user_id"],"email",email_id,{"mode":payload.mode,"reason":type(exc).__name__});db.commit()
        raise HTTPException(502,"Email context could not be loaded for the AI draft") from exc
    audit(db,request,"email.reply.assist","success",principal["user_id"],"email",email_id,{"mode":payload.mode,"provider":row.mailbox.provider,"has_employee_draft":bool(payload.body.strip()),"input_word_count":len(payload.body.split())});db.commit()
    return {"body":result,"mode":payload.mode}
@router.post("/emails/{email_id}/reply",dependencies=[admin])
async def send_email_reply(email_id:int,payload:ReplyInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=require_email_scope(db,principal,db.get(Email,email_id))
    if row.folder!="inbox":raise HTTPException(409,"Replies can only be sent to incoming mailbox messages")
    if not payload.body.strip():raise HTTPException(422,"Reply body cannot be empty")
    recipient=parseaddr(row.sender)[1]
    if not recipient or "\r" in recipient or "\n" in recipient:raise HTTPException(422,"The original sender address is invalid")
    settings=get_settings()
    try:
        strategy,refresh_token=_email_strategy(row,settings)
        subject=row.subject if row.subject.casefold().startswith("re:") else f"Re: {row.subject}"
        await strategy.send_reply(row.mailbox.address,row.message_id,recipient,subject,payload.body.strip(),row.internet_message_id,row.references,row.conversation_id)
        _save_refreshed_mailbox_token(row,strategy,refresh_token,settings)
    except Exception as exc:
        audit(db,request,"email.reply.send","failed",principal["user_id"],"email",email_id,{"provider":row.mailbox.provider,"reason":type(exc).__name__});db.commit()
        provider_error=str(exc).lower()
        if row.mailbox.provider=="microsoft" and any(reason in provider_error for reason in ("aadsts70000","unauthorized or expired","erroraccessdenied")):
            raise HTTPException(409,"Outlook needs Mail.Send permission. Reconnect this mailbox and approve Mail.Send, then retry. If it still fails, ask your Microsoft admin to verify the Mail.Send permission and mailbox access policy.") from exc
        raise HTTPException(502,"Reply could not be sent through the mailbox provider") from exc
    row.status=EmailStatus.REPLIED;row.replied_at=datetime.now(timezone.utc)
    calendar_row=db.scalar(select(BusinessCalendar).where(BusinessCalendar.mailbox_id==row.mailbox_id)) or db.scalar(select(BusinessCalendar).where(BusinessCalendar.mailbox_id.is_(None)))
    calendar=Calendar(timezone=row.mailbox.timezone,start=dt_time.fromisoformat(calendar_row.workday_start) if calendar_row else dt_time(9),end=dt_time.fromisoformat(calendar_row.workday_end) if calendar_row else dt_time(18),weekdays=tuple(calendar_row.weekdays) if calendar_row else (0,1,2,3,4),holidays=frozenset(date.fromisoformat(day) for day in calendar_row.holidays) if calendar_row else frozenset())
    rules=list(db.scalars(select(SLARule)));thresholds={rule.tier:rule.threshold_hours for rule in rules};business_only=all(rule.business_hours_only for rule in rules) if rules else True
    row.pending_hours=elapsed_hours(row.received_time,row.replied_at,calendar,business_only);row.sla_tier=tier_for(row.pending_hours,thresholds or None)
    audit(db,request,"email.reply.send","success",principal["user_id"],"email",email_id,{"provider":row.mailbox.provider});db.commit()
    return {"sent":True,"recipient":recipient,"replied_at":_utc_timestamp(row.replied_at)}
@router.patch("/emails/{email_id}/assignment",dependencies=[admin])
def assign_email(email_id:int,request:Request,employee_id:int|None=None,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Email,email_id)
    if not row:raise HTTPException(404,"Email not found")
    if employee_id is not None and not db.get(Employee,employee_id):raise HTTPException(404,"Employee not found")
    row.assigned_employee_id=employee_id;audit(db,request,"email.assignment.update","success",principal["user_id"],"email",email_id,{"employee_id":employee_id});db.commit();return {"id":row.id,"assigned_employee_id":employee_id}
@router.patch("/emails/{email_id}/status",dependencies=[admin])
def update_email_status(email_id:int,payload:dict,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Email,email_id)
    if not row: raise HTTPException(404,"Email not found")
    try: status=EmailStatus(str(payload.get("status", "")).lower())
    except ValueError: raise HTTPException(422,"Status must be pending, replied, or ignored")
    row.status=status
    if status != EmailStatus.REPLIED: row.replied_at=None
    audit(db,request,"email.status.update","success",principal["user_id"],"email",email_id,{"status":status.value})
    db.commit()
    return {"id":row.id,"status":status.value}
@router.get("/mailboxes",response_model=list[MailboxOut],dependencies=[admin])
def mailboxes(db:Session=Depends(get_db)):return list(db.scalars(select(Mailbox).order_by(Mailbox.address)))
@router.get("/mailbox-options",dependencies=[viewer])
def mailbox_options(principal:dict=viewer,db:Session=Depends(get_db)):
    allowed=mailbox_scope(db,principal);scope=[] if allowed is None else [Mailbox.id.in_(allowed)]
    return [{"id":row.id,"address":row.address,"display_name":row.display_name} for row in db.scalars(select(Mailbox).where(*scope).order_by(Mailbox.address))]
@router.post("/mailboxes",response_model=MailboxOut,dependencies=[admin],status_code=201)
def create_mailbox(payload:MailboxCreate,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    if db.scalar(select(Mailbox).where(Mailbox.address==payload.address)):raise HTTPException(409,ui_text(db,"api.error.mailbox_exists"))
    values=payload.model_dump(exclude={"azure_client_id","azure_tenant_id","azure_client_secret"});row=Mailbox(**values);db.add(row);db.flush()
    if payload.azure_client_id:
        row.azure_client_id=payload.azure_client_id.strip();row.azure_tenant_id=payload.azure_tenant_id.strip();set_mailbox_azure_secret(row,payload.azure_client_secret)
    audit(db,request,"mailbox.create","success",principal["user_id"],"mailbox",row.id,{"provider":row.provider});db.commit();db.refresh(row);return row
@router.patch("/mailboxes/{mailbox_id}",response_model=MailboxOut,dependencies=[admin])
def update_mailbox(mailbox_id:int,payload:MailboxUpdate,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Mailbox,mailbox_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.mailbox_missing"))
    values=payload.model_dump(exclude_unset=True,exclude={"azure_client_id","azure_tenant_id","azure_client_secret"})
    for key,value in values.items():setattr(row,key,value)
    if any(value is not None for value in (payload.azure_client_id,payload.azure_tenant_id,payload.azure_client_secret)):
        if row.provider!="microsoft":raise HTTPException(422,"Azure credentials require a Microsoft mailbox")
        client_id=(payload.azure_client_id or row.azure_client_id or "").strip();tenant_id=(payload.azure_tenant_id or row.azure_tenant_id or "").strip()
        if not client_id or not tenant_id or not (payload.azure_client_secret or row.azure_secret_ciphertext):raise HTTPException(422,"Azure Client ID, Tenant ID, and Client Secret are required")
        row.azure_client_id=client_id;row.azure_tenant_id=tenant_id
        if payload.azure_client_secret:set_mailbox_azure_secret(row,payload.azure_client_secret)
    audit(db,request,"mailbox.update","success",principal["user_id"],"mailbox",row.id,{"status":row.status.value});db.commit();db.refresh(row);return row
@router.delete("/mailboxes/{mailbox_id}",dependencies=[admin],status_code=204)
def delete_mailbox(mailbox_id:int,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Mailbox,mailbox_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.mailbox_missing"))
    email_ids=select(Email.id).where(Email.mailbox_id==mailbox_id)
    db.execute(delete(EscalationEvent).where(EscalationEvent.email_id.in_(email_ids)))
    db.execute(delete(EmailRecipient).where(EmailRecipient.email_id.in_(email_ids)))
    db.execute(delete(Email).where(Email.mailbox_id==mailbox_id))
    db.execute(delete(ConversationAIReview).where(ConversationAIReview.mailbox_id==mailbox_id))
    db.execute(delete(SyncLog).where(SyncLog.mailbox_id==mailbox_id))
    db.execute(delete(BusinessCalendar).where(BusinessCalendar.mailbox_id==mailbox_id))
    db.execute(delete(ManagerMailboxAccess).where(ManagerMailboxAccess.mailbox_id==mailbox_id))
    from app.models.entities import OAuthTransaction
    db.execute(delete(OAuthTransaction).where(OAuthTransaction.mailbox_id==mailbox_id))
    db.delete(row);audit(db,request,"mailbox.delete","success",principal["user_id"],"mailbox",mailbox_id,{"provider":row.provider});db.commit();return None
def _delegated_graph_app(settings,authority_tenant:str|None=None):
    if not settings.azure_client_id:
        with SessionLocal() as db:message=ui_text(db,"api.error.graph_client_id_required")
        raise HTTPException(503,message)
    if not settings.azure_client_secret:raise HTTPException(503,"Microsoft Outlook web login requires AZURE_CLIENT_SECRET. Save the secret value from Entra App registration.")
    tenant=authority_tenant or settings.azure_tenant_id.strip() or "common"
    return delegated_graph_application(settings,tenant)
@router.post("/mailboxes/{mailbox_id}/oauth/start")
def start_mailbox_oauth(mailbox_id:int,request:Request,response:Response,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Mailbox,mailbox_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.mailbox_missing"))
    if row.provider!="microsoft":raise HTTPException(409,ui_text(db,"api.error.microsoft_provider_required"))
    settings=mailbox_graph_settings(row,get_settings());authority_tenant=delegated_authority_tenant(row.address,settings);app=_delegated_graph_app(settings,authority_tenant);state,binding=new_oauth_values()
    try:
        flow=app.initiate_auth_code_flow(delegated_auth_code_scopes(settings),redirect_uri=settings.graph_redirect_uri,state=state,login_hint=row.address,prompt="consent")
    except Exception as exc:
        raise HTTPException(503,"Microsoft Outlook login could not be prepared. Check delegated Mail.Read/User.Read permissions and the redirect URI.") from exc
    transaction=save_transaction(db,response,state,binding,"microsoft",principal["user_id"],principal["sid"],mailbox_id,{"flow":flow,"authority_tenant":authority_tenant});audit(db,request,"oauth.start","success",principal["user_id"],"mailbox",mailbox_id,{"provider":"microsoft","transaction_id":transaction.id,"authority_tenant":authority_tenant});db.commit()
    return {"auth_url":flow["auth_uri"],"redirect_uri":settings.graph_redirect_uri,"scopes":" ".join(delegated_auth_code_scopes(settings))}
@router.get("/graph/oauth/callback")
def graph_oauth_callback(request:Request,db:Session=Depends(get_db)):
    try:transaction,payload=consume_transaction(db,request,request.query_params.get("state"),"microsoft");db.commit()
    except HTTPException:
        audit(db,request,"oauth.callback","denied",details={"provider":"microsoft","reason":"invalid_transaction"});db.commit();return _oauth_error(db,"oauth.failed.title")
    row=db.get(Mailbox,transaction.mailbox_id);settings=mailbox_graph_settings(row,get_settings()) if row else get_settings();app=_delegated_graph_app(settings,payload.get("authority_tenant"))
    if request.query_params.get("error"):
        detail=request.query_params.get("error_description") or request.query_params.get("error")
        audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"provider_denied"});db.commit();return _oauth_error(db,"oauth.failed.title",400,detail)
    try:result=app.acquire_token_by_auth_code_flow(payload["flow"],dict(request.query_params))
    except Exception:
        audit(db,request,"oauth.callback","failed",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"invalid_response"});db.commit();return _oauth_error(db,"oauth.failed.title")
    if "access_token" not in result:
        audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"token_exchange"});db.commit();return _oauth_error(db,"oauth.failed.title",400,str(result.get("error_description") or result.get("error") or "Microsoft token exchange failed"))
    if "refresh_token" not in result:
        audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"refresh_token_missing"});db.commit();return _oauth_error_detail(db,"oauth.failed.title","oauth.refresh_token_missing")
    try:
        profile=httpx.get("https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName",headers={"Authorization":f"Bearer {result['access_token']}"},timeout=30,follow_redirects=False);profile.raise_for_status();identity=profile.json()
    except Exception:
        audit(db,request,"oauth.callback","failed",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"identity_check"});db.commit();return _oauth_error(db,"oauth.failed.title",502)
    row=db.get(Mailbox,transaction.mailbox_id);account=(identity.get("mail") or identity.get("userPrincipalName") or "").lower();claims=result.get("id_token_claims",{})
    expected_tenant=settings.azure_tenant_id.strip().lower();actual_tenant=str(claims.get("tid","")).lower();personal_authority=payload.get("authority_tenant")=="consumers";tenant_mismatch=not personal_authority and expected_tenant not in {"","common","organizations","consumers"} and actual_tenant!=expected_tenant
    # Consumer accounts can omit oid or use a different subject namespace than
    # the Graph /me id. The verified mailbox address is the binding for MSA;
    # retain the stronger immutable-id check for organizational tenants.
    immutable_mismatch=(
        not identity.get("id")
        or (not personal_authority and (not claims.get("oid") or identity.get("id")!=claims.get("oid")))
    )
    if not row or account!=row.address.lower() or tenant_mismatch or immutable_mismatch:
        expected_account=row.address.lower() if row else "removed mailbox"
        detail=f"Expected {expected_account}; Microsoft connected {account or 'an account without a mailbox address'}"
        audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"microsoft","reason":"account_mismatch"});db.commit();return _oauth_error(db,"oauth.failed.title",400,detail)
    row.graph_auth_type="delegated";set_mailbox_token(row,result["refresh_token"],settings);row.provider_subject_id=identity.get("id");row.provider_tenant_id=claims.get("tid");row.delta_link=None;row.last_sync_error=None;audit(db,request,"oauth.callback","success",transaction.user_id,"mailbox",row.id,{"provider":"microsoft"});db.commit()
    response=HTMLResponse(f"<h2>{escape(ui_text(db,'oauth.connected.title'))}</h2><p>{escape(account)}</p><p>{escape(ui_text(db,'oauth.connected.body'))}</p>");clear_oauth_cookie(response);return response
@router.post("/mailboxes/{mailbox_id}/gmail/oauth/start")
def start_gmail_oauth(mailbox_id:int,request:Request,response:Response,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Mailbox,mailbox_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.mailbox_missing"))
    if row.provider!="gmail":raise HTTPException(409,ui_text(db,"api.error.gmail_provider_required"))
    settings=get_settings()
    if not settings.google_client_id or not settings.google_client_secret:raise HTTPException(503,ui_text(db,"api.error.gmail_credentials_missing"))
    state,binding=new_oauth_values();verifier,challenge=pkce_pair();transaction=save_transaction(db,response,state,binding,"gmail",principal["user_id"],principal["sid"],mailbox_id,{"code_verifier":verifier});audit(db,request,"oauth.start","success",principal["user_id"],"mailbox",mailbox_id,{"provider":"gmail","transaction_id":transaction.id});db.commit()
    auth_url="https://accounts.google.com/o/oauth2/v2/auth?"+urlencode({"client_id":settings.google_client_id,"redirect_uri":settings.google_redirect_uri,"response_type":"code","scope":" ".join(gmail_scopes(settings)),"access_type":"offline","prompt":"consent","include_granted_scopes":"true","login_hint":row.address,"state":state,"code_challenge":challenge,"code_challenge_method":"S256"})
    return {"auth_url":auth_url,"redirect_uri":settings.google_redirect_uri,"scopes":settings.gmail_scopes}
@router.get("/gmail/oauth/callback")
async def gmail_oauth_callback(request:Request,db:Session=Depends(get_db)):
    settings=get_settings()
    try:transaction,payload=consume_transaction(db,request,request.query_params.get("state"),"gmail");db.commit()
    except HTTPException:
        state_hash=_digest(request.query_params.get("state", "")) if request.query_params.get("state") else ""
        replay=db.scalar(select(OAuthTransaction).where(OAuthTransaction.state_hash==state_hash,OAuthTransaction.provider=="gmail")) if state_hash else None
        replay_mailbox=db.get(Mailbox,replay.mailbox_id) if replay else None
        if replay and replay.consumed_at and replay_mailbox and replay_mailbox.graph_auth_type=="gmail_oauth":
            return HTMLResponse(f"<h2>{escape(ui_text(db,'gmail.oauth.connected.title'))}</h2><p>{escape(replay_mailbox.address)}</p><p>{escape(ui_text(db,'gmail.oauth.connected.body'))}</p>")
        audit(db,request,"oauth.callback","denied",details={"provider":"gmail","reason":"invalid_transaction"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title",body_key="gmail.oauth.expired.body")
    if request.query_params.get("error"):audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"gmail","reason":"provider_denied"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title")
    try:
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            response=await client.post("https://oauth2.googleapis.com/token",data={"code":request.query_params.get("code",""),"client_id":settings.google_client_id,"client_secret":settings.google_client_secret,"redirect_uri":settings.google_redirect_uri,"grant_type":"authorization_code","code_verifier":payload["code_verifier"]})
            result=response.json()
            if response.status_code>=400 or "refresh_token" not in result or "access_token" not in result:
                audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"gmail","reason":"token_exchange"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title")
            profile_response=await client.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",headers={"Authorization":f"Bearer {result['access_token']}"})
            identity_response=await client.get("https://openidconnect.googleapis.com/v1/userinfo",headers={"Authorization":f"Bearer {result['access_token']}"})
    except Exception:
        audit(db,request,"oauth.callback","failed",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"gmail","reason":"invalid_response"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title",502)
    if profile_response.status_code>=400 or identity_response.status_code>=400:audit(db,request,"oauth.callback","failed",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"gmail","reason":"identity_check"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title",502)
    row=db.get(Mailbox,transaction.mailbox_id)
    if not row:return _oauth_error(db,"gmail.oauth.failed.title",404)
    account=profile_response.json().get("emailAddress","")
    identity=identity_response.json()
    if account.lower()!=row.address.lower() or identity.get("email","").lower()!=row.address.lower() or identity.get("email_verified") is not True:audit(db,request,"oauth.callback","denied",transaction.user_id,"mailbox",transaction.mailbox_id,{"provider":"gmail","reason":"account_mismatch"});db.commit();return _oauth_error(db,"gmail.oauth.failed.title")
    row.graph_auth_type="gmail_oauth";set_mailbox_token(row,result["refresh_token"],settings);row.provider_subject_id=identity.get("sub");row.provider_tenant_id=None;row.delta_link=None;row.last_sync_error=None;audit(db,request,"oauth.callback","success",transaction.user_id,"mailbox",row.id,{"provider":"gmail"});db.commit()
    response=HTMLResponse(f"<h2>{escape(ui_text(db,'gmail.oauth.connected.title'))}</h2><p>{escape(account)}</p><p>{escape(ui_text(db,'gmail.oauth.connected.body'))}</p>");clear_oauth_cookie(response);return response
@router.get("/employees/performance",dependencies=[viewer])
def employee_performance(sort_by:str="employee",order:str=Query("asc",pattern="^(asc|desc)$"),principal:dict=viewer,db:Session=Depends(get_db)):
    rows=EmailRepository(db).employee_performance(mailbox_scope(db,principal));allowed={"employee","total","average_reply_time","pending","critical","resolved"};key=sort_by if sort_by in allowed else "employee";return sorted(rows,key=lambda x:x[key],reverse=order=="desc")
@router.get("/employees/reply-rate",dependencies=[viewer])
def employee_reply_rate(principal:dict=viewer,db:Session=Depends(get_db)):
    return EmailRepository(db).all_employee_reply_rate(mailbox_scope(db,principal))
@router.get("/employees/connections",dependencies=[viewer])
def employee_connections(principal:dict=viewer,db:Session=Depends(get_db)):
    return EmailRepository(db).employee_connections(mailbox_scope(db,principal))
@router.get("/dashboard/growth",dependencies=[viewer])
def dashboard_growth(principal:dict=viewer,db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc);start=(now-timedelta(days=13)).replace(hour=0,minute=0,second=0,microsecond=0)
    scope=mailbox_scope(db,principal);filters=[Email.folder=="inbox",Email.received_time>=start]
    if scope is not None: filters.append(Email.mailbox_id.in_(scope))
    buckets={(start+timedelta(days=i)).date().isoformat():{"date":(start+timedelta(days=i)).date().isoformat(),"incoming":0,"replied":0,"pending":0,"ignored":0} for i in range(14)}
    for row in db.scalars(select(Email).where(*filters)):
        bucket=buckets.get(row.received_time.astimezone(timezone.utc).date().isoformat())
        if bucket:
            bucket["incoming"]+=1;bucket[row.status.value if row.status.value in {"replied","pending","ignored"} else "pending"]+=1
    return list(buckets.values())
@router.get("/dashboard/insights",dependencies=[viewer])
def dashboard_insights(principal:dict=viewer,db:Session=Depends(get_db)):
    return {"top_senders":EmailRepository(db).sender_insights(mailbox_scope(db,principal))}
@router.get("/employees",dependencies=[viewer])
def employees(db:Session=Depends(get_db)):return [{"id":x.id,"name":x.name,"email":x.email,"department":x.department,"active":x.active} for x in db.scalars(select(Employee).where(func.lower(func.trim(Employee.email)).like("%@indianinfotech.org")).order_by(Employee.department,Employee.name))]
@router.post("/employees",dependencies=[admin],status_code=201)
def create_employee(payload:EmployeeInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    email=str(payload.email).lower()
    if not is_company_employee_email(email):raise HTTPException(422,"Employees must use an @indianinfotech.org email address")
    row=db.scalar(select(Employee).where(func.lower(Employee.email)==email))
    if row:
        row.name=payload.name;row.active=payload.active;row.email=email;row.department=payload.department.strip()
    else:
        row=Employee(name=payload.name,email=email,department=payload.department.strip(),active=payload.active);db.add(row)
    db.flush();audit(db,request,"employee.upsert","success",principal["user_id"],"employee",row.id,{"active":row.active,"department":row.department});db.commit();db.refresh(row);return {"id":row.id,"name":row.name,"email":row.email,"department":row.department,"active":row.active}
@router.patch("/employees/{employee_id}",dependencies=[admin])
def update_employee(employee_id:int,payload:EmployeeUpdate,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=db.get(Employee,employee_id)
    if not row:raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    values=payload.model_dump(exclude_unset=True)
    if payload.email:
        values["email"]=str(payload.email).lower()
        if db.scalar(select(Employee).where(func.lower(Employee.email)==values["email"],Employee.id!=employee_id)):raise HTTPException(409,ui_text(db,"api.error.employee_exists"))
    if values.get("active",row.active) and not is_company_employee_email(values.get("email",row.email)):
        raise HTTPException(422,"Employees must use an @indianinfotech.org email address")
    for key,value in values.items():setattr(row,key,value.strip() if key=="department" and value else value)
    audit(db,request,"employee.update","success",principal["user_id"],"employee",row.id,{"active":row.active,"department":row.department});db.commit();db.refresh(row);return {"id":row.id,"name":row.name,"email":row.email,"department":row.department,"active":row.active}
@router.get("/employees/{employee_id}/performance",dependencies=[viewer])
def one_employee(employee_id:int,principal:dict=viewer,db:Session=Depends(get_db)):
    rows=[x for x in EmailRepository(db).employee_performance(mailbox_scope(db,principal)) if x["id"]==employee_id]
    if not rows:raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    return rows[0]
@router.get("/employees/{employee_id}/trend",dependencies=[viewer])
def employee_trend(employee_id:int,all_history:bool=False,year:int|None=Query(None,ge=2000,le=2100),principal:dict=viewer,db:Session=Depends(get_db)):
    if not db.get(Employee,employee_id):raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    return EmailRepository(db).employee_trend(employee_id,None if all_history else 365,mailbox_scope(db,principal),year)
@router.get("/employees/{employee_id}/hourly-activity",dependencies=[viewer])
def employee_hourly_activity(employee_id:int,day:date=Query(default_factory=date.today),principal:dict=viewer,db:Session=Depends(get_db)):
    if not db.get(Employee,employee_id):raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    return EmailRepository(db).employee_hourly_activity(employee_id,day,mailbox_scope(db,principal))
@router.get("/employees/{employee_id}/daily-senders",dependencies=[viewer])
def employee_daily_senders(employee_id:int,day:date=Query(default_factory=date.today),principal:dict=viewer,db:Session=Depends(get_db)):
    if not db.get(Employee,employee_id):raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    return EmailRepository(db).employee_daily_senders(employee_id,day,mailbox_scope(db,principal))
@router.get("/reports/{period}",dependencies=[viewer])
def report(period:str,dimension:str=Query(...,pattern="^(department|employee|customer|mailbox)$"),principal:dict=viewer,db:Session=Depends(get_db),department:str|None=None,employee_id:int|None=None):
    if period not in {"daily","weekly","monthly"}:raise HTTPException(422,ui_text(db,"api.error.report_period_invalid"))
    cutoff=_report_cutoff(period)
    allowed=mailbox_scope(db,principal);scope=[] if allowed is None else [Email.mailbox_id.in_(allowed)]
    if department:scope.append(or_(Email.employee.has(Employee.department==department),Email.recipients.any(EmailRecipient.employee.has(Employee.department==department))))
    if employee_id is not None:scope.append(employee_mail_scope(employee_id))
    limit=get_settings().max_report_rows;rows=list(db.scalars(select(Email).options(joinedload(Email.mailbox),joinedload(Email.employee),selectinload(Email.recipients).joinedload(EmailRecipient.employee)).where(Email.folder=="inbox",Email.received_time>=cutoff,*scope).limit(limit+1)))
    if len(rows)>limit:raise HTTPException(413,"Report exceeds configured row limit")
    unassigned=ui_text(db,"report.unassigned")
    key=lambda e: (e.employee.department or "General") if dimension=="department" and e.employee else "Unassigned" if dimension=="department" else e.employee.name if dimension=="employee" and e.employee else unassigned if dimension=="employee" else e.sender if dimension=="customer" else e.mailbox.address
    grouped={}
    if dimension in {"department","employee"}:
        employee_scope=[] if allowed is None else [select(Email.id).where(Email.mailbox_id.in_(allowed),employee_mail_scope(Employee.id)).correlate(Employee).exists()]
        employee_scope.append(func.lower(func.trim(Employee.email)).like("%@indianinfotech.org"))
        if department:employee_scope.append(Employee.department==department)
        if employee_id is not None:employee_scope.append(Employee.id==employee_id)
        for employee in db.scalars(select(Employee).where(*employee_scope)):
            group_id=("employee",employee.id) if dimension=="employee" else employee.department or "General"
            grouped.setdefault(group_id,{"dimension":employee.name if dimension=="employee" else employee.department or "General","employee_id":employee.id,"department":employee.department or "General","total":0,"pending":0,"resolved":0,"replied_by_other":0,"ignored":0,"critical":0,"reply_hours":0.0})
    for e in rows:
        participants={recipient.employee_id:recipient.employee for recipient in e.recipients}
        if e.employee:participants[e.employee.id]=e.employee
        if dimension in {"employee","department"}:
            entries={}
            for person in participants.values():
                if not is_company_employee_email(person.email):continue
                if employee_id is not None and person.id!=employee_id:continue
                if department and person.department!=department:continue
                group_id=("employee",person.id) if dimension=="employee" else person.department or "General"
                if group_id not in entries:entries[group_id]=[person,False]
                entries[group_id][1] |= person.id==e.assigned_employee_id
        else:entries={key(e):[None,True]}
        if not participants and dimension in {"employee","department"}:entries={key(e):[None,True]}
        for group_id,(person,owns_credit) in entries.items():
            name=(person.name if dimension=="employee" else person.department or "General") if person else key(e)
            bucket=grouped.setdefault(group_id,{"dimension":name,"employee_id":person.id if dimension=="employee" and person else None,"department":person.department if dimension=="employee" and person else None,"total":0,"pending":0,"resolved":0,"replied_by_other":0,"ignored":0,"critical":0,"reply_hours":0.0})
            credited=e.status==EmailStatus.REPLIED and owns_credit
            bucket["total"]+=1;bucket["pending"]+=int(e.status==EmailStatus.PENDING);bucket["resolved"]+=int(credited);bucket["replied_by_other"]+=int(e.status==EmailStatus.REPLIED and not owns_credit);bucket["ignored"]+=int(e.status==EmailStatus.IGNORED);bucket["critical"]+=int(e.status==EmailStatus.PENDING and e.sla_tier==SLATier.CRITICAL)
            if credited:bucket["reply_hours"]+=e.pending_hours
    ordered=sorted(grouped.values(),key=lambda row:((row.get("department") or "").casefold(),row["dimension"].casefold()))
    latest_received=db.scalar(select(func.max(Email.received_time)).where(Email.folder=="inbox",*scope))
    return {"period":period,"dimension":dimension,"period_start":cutoff,"latest_received_at":_utc_timestamp(latest_received),"rows":[{"dimension":x["dimension"],**({"employee_id":x["employee_id"],"department":x["department"]} if dimension=="employee" else {}),"total_received":x["total"],"replied":x["resolved"],"not_replied":x["pending"],"replied_by_other":x["replied_by_other"],"ignored":x["ignored"],"critical":x["critical"],"reply_rate":round(x["resolved"]*100/(x["resolved"]+x["pending"]+x["replied_by_other"]),1) if x["resolved"]+x["pending"]+x["replied_by_other"] else 0,"average_reply_hours":x["reply_hours"]/x["resolved"] if x["resolved"] else 0} for x in ordered]}

@router.get("/reports/{period}/employees/{employee_id}/mail",dependencies=[viewer])
def employee_mail_report(period:str,employee_id:int,principal:dict=viewer,db:Session=Depends(get_db)):
    if period not in {"daily","weekly","monthly"}: raise HTTPException(422,ui_text(db,"api.error.report_period_invalid"))
    if not db.get(Employee,employee_id): raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    cutoff=_report_cutoff(period); allowed=mailbox_scope(db,principal); scope=[Email.folder=="inbox",Email.received_time>=cutoff,employee_mail_scope(employee_id)]
    if allowed is not None: scope.append(Email.mailbox_id.in_(allowed))
    rows=list(db.scalars(select(Email).options(joinedload(Email.mailbox),joinedload(Email.employee)).where(*scope).order_by(Email.received_time.desc()).limit(get_settings().max_report_rows)))
    return {"period":period,"period_start":cutoff,"employee_id":employee_id,"mails":[{"id":e.id,"sender":e.sender,"receiver":e.receiver,"subject":e.subject or "(no subject)","received_at":_utc_timestamp(e.received_time),"status":e.status.value,"status_label":("Replied by you" if e.assigned_employee_id==employee_id else f"Not replied by you · Replied by {e.employee.name if e.employee else 'another employee'}") if e.status==EmailStatus.REPLIED else e.status.value,"replied_by":e.employee.name if e.status==EmailStatus.REPLIED and e.employee else None,"replied_by_you":e.status==EmailStatus.REPLIED and e.assigned_employee_id==employee_id,"classification":e.classification.value if e.classification else None,"sla_tier":e.sla_tier.value if e.sla_tier else None,"reply_hours":e.pending_hours,"reason":f"{e.classification.value if e.classification else 'Customer'} mail · {e.sla_tier.value if e.sla_tier else 'healthy'} SLA · {e.status.value}"} for e in rows]}
def _xlsx_value(value):
    if isinstance(value,str) and value.startswith(("=","+","-","@","\t","\r","\n")):return "'"+value
    return value
@router.get("/reports/{period}/export",dependencies=[viewer])
def export_report(period:str,request:Request,dimension:str=Query(...,pattern="^(department|employee|customer|mailbox)$"),format:str=Query("xlsx",pattern="^(xlsx|csv|pdf)$"),principal:dict=viewer,db:Session=Depends(get_db),department:str|None=None,employee_id:int|None=None):
    payload=report(period,dimension,principal,db,department,employee_id);rows=payload["rows"];stream=BytesIO()
    if format=="csv":
        text_stream=StringIO(newline="");headers=list(rows[0]) if rows else (["dimension","employee_id","department","total_received","replied","not_replied","replied_by_other","ignored","critical","reply_rate","average_reply_hours"] if dimension=="employee" else ["dimension","total_received","replied","not_replied","replied_by_other","ignored","critical","reply_rate","average_reply_hours"]);writer=csv.DictWriter(text_stream,fieldnames=headers);writer.writeheader()
        for row in rows:writer.writerow({key:_xlsx_value(value) for key,value in row.items()})
        stream.write(text_stream.getvalue().encode("utf-8-sig"));media="text/csv; charset=utf-8"
    elif format=="xlsx":
        workbook=Workbook();sheet=workbook.active;sheet.title=f"{period}-{dimension}";headers=list(rows[0]) if rows else (["dimension","employee_id","department","total_received","replied","not_replied","replied_by_other","ignored","critical","reply_rate","average_reply_hours"] if dimension=="employee" else ["dimension","total_received","replied","not_replied","replied_by_other","ignored","critical","reply_rate","average_reply_hours"]);sheet.append(headers)
        for row in rows:sheet.append([_xlsx_value(row.get(x)) for x in headers])
        sheet.freeze_panes="A2";workbook.save(stream);media="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        styles=getSampleStyleSheet();story=[Paragraph(escape(ui_text(db,"report.pdf.heading",period=period.title(),dimension=dimension.title())),styles["Heading1"])]
        for row in rows:
            for key,value in row.items():story.append(Paragraph(f"<b>{escape(key.replace('_',' ').title())}:</b> {escape(str(value))}",styles["BodyText"]))
            story.append(Spacer(1,16))
        SimpleDocTemplate(stream,pagesize=A4,title=ui_text(db,"report.pdf.title")).build(story);media="application/pdf"
    stream.seek(0);audit(db,request,"report.export","success",principal["user_id"],"report",f"{period}:{dimension}",{"format":format,"rows":len(rows)});db.commit();return StreamingResponse(stream,media_type=media,headers={"Content-Disposition":f'attachment; filename="oeis-{period}-{dimension}.{format}"',"Cache-Control":"no-store"})
@router.get("/settings/ai-provider",dependencies=[admin])
def get_ai_provider(db:Session=Depends(get_db)):
    return provider_status(db)
@router.patch("/settings/ai-provider",dependencies=[admin])
def update_ai_provider(payload:dict,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    provider=payload.get("provider");model=payload.get("model");api_key=payload.get("api_key")
    if not isinstance(provider,str) or not isinstance(model,str) or api_key is not None and (not isinstance(api_key,str) or len(api_key)>4096):
        raise HTTPException(422,"Invalid AI provider settings")
    try:result=save_ai_settings(db,provider,model,api_key.strip() if api_key else None)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    retry_count=0
    for review in db.scalars(select(ConversationAIReview).where(ConversationAIReview.status=="failed")):
        review.status="pending";review.error_code=None;review.analyzed_at=None;review.analysis=None;review.rubric=None;retry_count+=1
    audit(db,request,"settings.ai_provider.update","success",principal["user_id"],"ai_provider",1,{"provider":provider,"model":model,"reviews_queued":retry_count});db.commit()
    result["reviews_queued"]=retry_count
    return result
@router.get("/reports/ai-review/status",dependencies=[viewer])
def ai_review_status(request:Request,db:Session=Depends(get_db)):
    setting=db.get(AIReviewSetting,1)
    settings=active_ai_settings(db,get_settings())
    scheduler=getattr(request.app.state,"scheduler",None);job=scheduler.get_job("conversation-ai-review") if scheduler else None
    return {"enabled":bool(setting and setting.enabled),"provider_configured":bool(settings.ai_api_key),"scheduler_enabled":bool(job and job.next_run_time)}
@router.patch("/reports/ai-review/status",dependencies=[admin])
def update_ai_review_status(payload:dict,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    enabled=payload.get("enabled")
    if not isinstance(enabled,bool):raise HTTPException(422,"enabled must be a boolean")
    if enabled and not active_ai_settings(db,get_settings()).ai_api_key:raise HTTPException(503,"Configure the AI provider before enabling continuous reviews")
    setting=db.get(AIReviewSetting,1) or AIReviewSetting(id=1);setting.enabled=enabled
    if enabled:setting.approved_by=principal["user_id"];setting.approved_at=datetime.now(timezone.utc)
    db.add(setting);audit(db,request,"report.ai_review.setting","success",principal["user_id"],"ai_review_setting",1,{"enabled":enabled});db.commit()
    settings=active_ai_settings(db,get_settings());scheduler=getattr(request.app.state,"scheduler",None);job=scheduler.get_job("conversation-ai-review") if scheduler else None
    return {"enabled":setting.enabled,"provider_configured":bool(settings.ai_api_key),"scheduler_enabled":bool(job and job.next_run_time)}
@router.get("/reports/{period}/employees/{employee_id}/ai-review",dependencies=[viewer])
def employee_ai_review(period:str,employee_id:int,page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),principal:dict=viewer,db:Session=Depends(get_db)):
    if period not in {"daily","weekly","monthly"}:raise HTTPException(422,ui_text(db,"api.error.report_period_invalid"))
    setting=db.get(AIReviewSetting,1)
    employee=db.get(Employee,employee_id)
    if not employee:raise HTTPException(404,ui_text(db,"api.error.employee_missing"))
    cutoff=_report_cutoff(period)
    allowed=mailbox_scope(db,principal);scope=[] if allowed is None else [Email.mailbox_id.in_(allowed)]
    incoming=list(db.scalars(select(Email).where(Email.folder=="inbox",Email.classification==Classification.CUSTOMER,Email.assigned_employee_id==employee_id,Email.received_time>=cutoff,*scope).order_by(Email.received_time,Email.id)))
    warning_rule=db.scalar(select(SLARule).where(SLARule.tier==SLATier.WARNING))
    keys=[];subjects={};messages_by_key={}
    for email in incoming:
        key=(email.mailbox_id,_report_conversation_key(email))
        if key not in subjects:keys.append(key);subjects[key]=email.subject;messages_by_key[key]=[]
        messages_by_key[key].append(email)
    cache_filters=[ConversationAIReview.employee_id==employee_id]
    if allowed is not None:cache_filters.append(ConversationAIReview.mailbox_id.in_(allowed))
    cached=list(db.scalars(select(ConversationAIReview).where(*cache_filters)))
    by_key={(item.mailbox_id,item.conversation_key):item for item in cached}
    reviews=[];reviewed=failed=0;quality_rubrics=[];quality_threads=0
    for mailbox_id,conversation_key in keys:
        item=by_key.get((mailbox_id,conversation_key))
        last_activity=_review_activity(db,_thread_rows(db,mailbox_id,conversation_key,messages_by_key[(mailbox_id,conversation_key)]))
        is_current=bool(item and item.status=="ready" and _utc_timestamp(item.last_message_at)>=last_activity and (item.rubric or {}).get("review_version")==REVIEW_VERSION)
        if is_current:reviewed+=1
        elif item and item.status=="failed":failed+=1
        first_message=messages_by_key[(mailbox_id,conversation_key)][0]
        if any(message.status==EmailStatus.REPLIED for message in messages_by_key[(mailbox_id,conversation_key)]):
            quality_threads+=1
            if is_current and item.rubric:quality_rubrics.append(item.rubric)
        reviews.append({"subject":subjects[(mailbox_id,conversation_key)],"sender":first_message.sender,"received_at":_utc_timestamp(first_message.received_time),"mailbox":first_message.mailbox.address,"status":"ready" if is_current else "pending" if not item or item.status=="ready" else item.status,"analysis":item.analysis if is_current else None,"rubric":item.rubric if is_current else None,"analyzed_at":_utc_timestamp(item.analyzed_at) if item and item.analyzed_at else None,"error":item.error_code if item and item.status=="failed" else None})
    total_pages=max(1,(len(reviews)+page_size-1)//page_size)
    work_score=_work_handling_score(incoming,warning_rule.threshold_hours if warning_rule else None,quality_rubrics,quality_threads)
    return {"employee":employee.name,"department":employee.department,"period":period,"enabled":bool(setting and setting.enabled),"conversation_count":len(keys),"reviewed_count":reviewed,"pending_count":len(keys)-reviewed-failed,"failed_count":failed,"work_score":work_score,"page":page,"page_size":page_size,"total_pages":total_pages,"reviews":reviews[(page-1)*page_size:page*page_size],"notice":"Scores are evidence-based coaching indicators, not compensation recommendations. Missing quality evidence remains unscored."}
@router.post("/reports/daily/send",dependencies=[admin])
async def send_daily(request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    from app.services.jobs import _daily_summary_job
    settings=get_settings()
    if not (settings.smtp_host and settings.smtp_username and settings.smtp_password) and not report_mailbox_available():raise HTTPException(503,"Connect an Outlook mailbox or configure SMTP to send reports")
    recipient=db.get(User,principal["user_id"])
    if not recipient or not recipient.email:raise HTTPException(409,"Your admin account needs an email address to receive the report")
    try:await asyncio.to_thread(_daily_summary_job,recipient.email)
    except Exception as exc:
        audit(db,request,"report.daily_send","failed",principal["user_id"],details={"reason":type(exc).__name__});db.commit()
        raise HTTPException(502,"Report delivery failed. Check the connected mailbox's Mail.Send permission and try again") from exc
    audit(db,request,"report.daily_send","sent",principal["user_id"]);db.commit();return {"status":"sent","recipient":recipient.email}
@router.get("/settings/sla-rules",dependencies=[viewer])
def get_sla(db:Session=Depends(get_db)):return list(db.scalars(select(SLARule).order_by(SLARule.threshold_hours)))
@router.patch("/settings/sla-rules",dependencies=[admin])
def update_sla(payload:list[SLARuleInput],request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    if payload and len({item.business_hours_only for item in payload})>1:raise HTTPException(422,"All SLA tiers must use the same business-hours policy")
    for item in payload:
        tier=SLATier(item.tier);row=db.scalar(select(SLARule).where(SLARule.tier==tier)) or SLARule(tier=tier);values=item.model_dump(exclude={"tier"})
        for k,v in values.items():setattr(row,k,v)
        db.add(row)
    audit(db,request,"settings.sla.update","success",principal["user_id"],details={"count":len(payload)});db.commit();return {"updated":len(payload)}
@router.get("/settings/classification-rules",dependencies=[viewer])
def get_classification(db:Session=Depends(get_db)):return list(db.scalars(select(ClassificationRule).order_by(ClassificationRule.priority)))
@router.patch("/settings/classification-rules",dependencies=[admin])
def update_classification(payload:list[ClassificationRuleInput],request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    db.execute(delete(ClassificationRule));db.add_all([ClassificationRule(name=x.name,priority=x.priority,field=x.field,pattern=x.pattern,classification=Classification(x.classification),active=x.active) for x in payload]);audit(db,request,"settings.classification.update","success",principal["user_id"],details={"count":len(payload)});db.commit();return {"updated":len(payload)}
@router.get("/settings/business-calendars",dependencies=[viewer])
def calendars(principal:dict=viewer,db:Session=Depends(get_db)):
    allowed=mailbox_scope(db,principal)
    scope=[] if allowed is None else [or_(BusinessCalendar.mailbox_id.is_(None),BusinessCalendar.mailbox_id.in_(allowed))]
    return list(db.scalars(select(BusinessCalendar).where(*scope).order_by(BusinessCalendar.id)))
@router.post("/settings/business-calendars",dependencies=[admin],status_code=201)
def create_calendar(payload:CalendarInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    row=BusinessCalendar(**payload.model_dump());db.add(row);db.flush();audit(db,request,"settings.calendar.create","success",principal["user_id"],"calendar",row.id);db.commit();db.refresh(row);return row
@router.patch("/settings/business-calendars",dependencies=[admin])
def update_calendars(payload:list[CalendarInput],request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    db.execute(delete(BusinessCalendar));db.add_all([BusinessCalendar(**x.model_dump()) for x in payload]);audit(db,request,"settings.calendars.update","success",principal["user_id"],details={"count":len(payload)});db.commit();return {"updated":len(payload)}
@router.get("/system/sync-settings",dependencies=[admin])
def get_sync_settings(request:Request):
    settings=get_settings();scheduler=getattr(request.app.state,"scheduler",None);job=scheduler.get_job("mailbox-sync") if scheduler else None
    return {"interval_seconds":settings.sync_interval_seconds,"scheduler_enabled":settings.scheduler_enabled,"next_sync":job.next_run_time if job and job.next_run_time else None}
@router.patch("/system/sync-settings",dependencies=[admin])
def update_sync_settings(payload:SyncSettingsInput,request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    values={"SYNC_INTERVAL_SECONDS":str(payload.interval_seconds),"SCHEDULER_ENABLED":str(payload.scheduler_enabled).lower()}
    try:_write_env_values(BACKEND_ENV,values)
    except OSError as exc:raise HTTPException(503,"Backend environment is read-only. Set SYNC_INTERVAL_SECONDS and SCHEDULER_ENABLED in the deployment environment.") from exc
    for key,value in values.items():os.environ[key]=value
    get_settings.cache_clear();settings=get_settings();scheduler=getattr(request.app.state,"scheduler",None)
    # The scheduler is owned by the application lifespan; this sync route may run in a worker thread.
    if scheduler:
        from app.services.jobs import sync_job
        apply_sync_settings(scheduler,sync_job,payload.interval_seconds,payload.scheduler_enabled)
        for job_id in ("daily-summary",):
            (scheduler.resume_job if payload.scheduler_enabled else scheduler.pause_job)(job_id)
    audit(db,request,"settings.sync.update","success",principal["user_id"],details={"interval_seconds":payload.interval_seconds,"scheduler_enabled":payload.scheduler_enabled});db.commit()
    job=scheduler.get_job("mailbox-sync") if scheduler else None
    return {"interval_seconds":settings.sync_interval_seconds,"scheduler_enabled":settings.scheduler_enabled,"next_sync":job.next_run_time if job and job.next_run_time else None}
@router.get("/audit-logs",dependencies=[viewer])
def audit_logs(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),principal:dict=viewer,db:Session=Depends(get_db)):
    allowed=mailbox_scope(db,principal);sync_scope=[] if allowed is None else [SyncLog.mailbox_id.in_(allowed)];email_scope=select(Email.id) if allowed is None else select(Email.id).where(Email.mailbox_id.in_(allowed))
    sync_rows=[{"id":f"sync-{x.id}","mailbox_id":x.mailbox_id,"date":_utc_timestamp(x.started_at),"action":x.action,"api_response":x.api_response,"errors":x.errors,"status":x.status,"emails_fetched":x.emails_fetched,"emails_new":x.emails_new} for x in db.scalars(select(SyncLog).where(*sync_scope))]
    escalation_rows=[{"id":f"escalation-{x.id}","mailbox_id":None,"date":_utc_timestamp(x.created_at),"action":"escalation","api_response":f"email_id={x.email_id};threshold={x.threshold};recipient={x.recipient_role}","errors":None,"status":"sent","emails_fetched":0,"emails_new":0} for x in db.scalars(select(EscalationEvent).where(EscalationEvent.email_id.in_(email_scope)))]
    rows=sorted(sync_rows+escalation_rows,key=lambda row:row["date"],reverse=True);return rows[(page-1)*page_size:page*page_size]
@router.get("/security/audit-events",dependencies=[admin])
def security_audit_events(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),db:Session=Depends(get_db)):
    rows=list(db.scalars(select(SecurityAuditEvent).order_by(SecurityAuditEvent.created_at.desc()).offset((page-1)*page_size).limit(page_size)))
    return [{"id":row.id,"actor_user_id":row.actor_user_id,"action":row.action,"object_type":row.object_type,"object_id":row.object_id,"outcome":row.outcome,"request_id":row.request_id,"details":row.details,"created_at":row.created_at} for row in rows]
@router.get("/escalations",dependencies=[viewer])
def escalations(principal:dict=viewer,db:Session=Depends(get_db)):
    allowed=mailbox_scope(db,principal);email_scope=select(Email.id) if allowed is None else select(Email.id).where(Email.mailbox_id.in_(allowed));rows=list(db.scalars(select(EscalationEvent).where(EscalationEvent.email_id.in_(email_scope)).order_by(EscalationEvent.created_at.desc())));return [{"id":x.id,"email_id":x.email_id,"threshold":x.threshold,"recipient_role":x.recipient_role,"created_at":x.created_at} for x in rows]
@router.post("/sync/trigger",dependencies=[admin])
async def trigger_sync(request:Request,principal:dict=admin,db:Session=Depends(get_db)):
    from app.services.jobs import run_sync_with_lease
    settings=get_settings();configured=list(db.scalars(select(Mailbox).where(Mailbox.status!=MailboxStatus.PAUSED)))
    if not configured:raise HTTPException(409,ui_text(db,"api.error.sync_no_mailbox"))
    microsoft_ready=all(bool((configured_settings:=mailbox_graph_settings(row,settings)).azure_client_id and (row.connected or configured_settings.azure_tenant_id and (configured_settings.azure_client_secret or configured_settings.azure_client_certificate_path))) for row in configured if row.provider=="microsoft")
    gmail_ready=all(bool(row.connected and settings.google_client_id and settings.google_client_secret) for row in configured if row.provider=="gmail")
    if not microsoft_ready or not gmail_ready:raise HTTPException(503,ui_text(db,"api.error.mail_credentials_missing"))
    started=datetime.now(timezone.utc)
    if not await run_sync_with_lease():raise HTTPException(409,"Synchronization is already running")
    logs=list(db.scalars(select(SyncLog).where(SyncLog.started_at>=started).order_by(SyncLog.started_at.desc())))
    result={"status":"completed","mailboxes_synced":len(logs),"failed_mailboxes":sum(1 for row in logs if row.status!="success"),"emails_fetched":sum(row.emails_fetched for row in logs),"emails_new":sum(row.emails_new for row in logs),"logs":[{"mailbox_id":row.mailbox_id,"status":row.status,"emails_fetched":row.emails_fetched,"emails_new":row.emails_new,"errors":"Synchronization failed" if row.errors else None} for row in logs]};audit(db,request,"sync.manual","success",principal["user_id"],details={"mailboxes":len(logs),"failed":result["failed_mailboxes"]});db.commit();return result
