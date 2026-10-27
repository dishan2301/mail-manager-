from contextlib import asynccontextmanager
import secrets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base,SessionLocal,engine
from app.core.security import hash_password
from app.models.entities import Classification,ClassificationRule,Role,SLARule,SLATier,User
from app.services.content import seed_ui_content
from app.services.jobs import conversation_ai_review_job,daily_summary_job,daily_ai_connection_job,sync_job
from app.services.scheduler import build_scheduler
from app.services.secrets import migrate_mailbox_token
from app.models.entities import Mailbox
from sqlalchemy import select,text
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlparse
def _origin_variants(value:str)->list[str]:
    parsed=urlparse(value)
    if not parsed.scheme or not parsed.netloc:return []
    hosts={parsed.hostname or ""}
    if parsed.hostname=="localhost":hosts.add("127.0.0.1")
    if parsed.hostname=="127.0.0.1":hosts.add("localhost")
    port=f":{parsed.port}" if parsed.port else ""
    return [f"{parsed.scheme}://{host}{port}" for host in hosts if host]
@asynccontextmanager
async def lifespan(app:FastAPI):
    if not settings.production:Base.metadata.create_all(engine)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as conn:
            employee_columns={row[1] for row in conn.execute(text("PRAGMA table_info(employees)"))}
            if "department" not in employee_columns:conn.execute(text("ALTER TABLE employees ADD COLUMN department VARCHAR(120) NOT NULL DEFAULT 'General'"))
            columns={row[1] for row in conn.execute(text("PRAGMA table_info(mailboxes)"))}
            if "graph_auth_type" not in columns:conn.execute(text("ALTER TABLE mailboxes ADD COLUMN graph_auth_type VARCHAR(20) DEFAULT 'application' NOT NULL"))
            if "graph_refresh_token" not in columns:conn.execute(text("ALTER TABLE mailboxes ADD COLUMN graph_refresh_token TEXT"))
            if "provider" not in columns:conn.execute(text("ALTER TABLE mailboxes ADD COLUMN provider VARCHAR(20) DEFAULT 'microsoft' NOT NULL"))
            for name,kind in (("token_ciphertext","TEXT"),("token_nonce","VARCHAR(64)"),("token_key_id","VARCHAR(64)"),("provider_subject_id","VARCHAR(128)"),("provider_tenant_id","VARCHAR(128)")):
                if name not in columns:conn.execute(text(f"ALTER TABLE mailboxes ADD COLUMN {name} {kind}"))
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.role==Role.ADMIN).limit(1)):
            db.add(User(email=settings.bootstrap_admin_email,name=settings.bootstrap_admin_name,password_hash=hash_password(settings.bootstrap_admin_password),role=Role.ADMIN,active=True))
        defaults={SLATier.HEALTHY:0,SLATier.WARNING:4,SLATier.OVERDUE:8,SLATier.CRITICAL:24}
        for tier,hours in defaults.items():
            if not db.scalar(select(SLARule).where(SLARule.tier==tier)):db.add(SLARule(tier=tier,threshold_hours=hours,business_hours_only=True,notify_manager_at_hours=8,notify_director_at_hours=24))
        if not db.scalar(select(ClassificationRule.id).limit(1)):
            defaults=[("OTP subject",10,"subject",r"\b(otp|verification code|one.time password)\b",Classification.OTP),("Auto sender",20,"sender",r"(^|[._-])(no.?reply|automated)([._-]|@)",Classification.NO_REPLY),("Newsletter",30,"subject",r"\b(newsletter|weekly digest)\b",Classification.NEWSLETTER),("Marketing",40,"subject",r"\b(sale|special offer|promotion|discount)\b",Classification.MARKETING),("LinkedIn",50,"domain",r"(^|\.)linkedin\.com$",Classification.LINKEDIN),("Amazon",60,"domain",r"(^|\.)amazon\.",Classification.AMAZON),("Microsoft",70,"domain",r"(^|\.)microsoft\.com$",Classification.MICROSOFT),("Google alerts",80,"sender",r"googlealerts-noreply",Classification.GOOGLE)]
            db.add_all([ClassificationRule(name=n,priority=p,field=f,pattern=x,classification=c,active=True) for n,p,f,x,c in defaults])
        seed_ui_content(db)
        for mailbox in db.scalars(select(Mailbox)):
            migrate_mailbox_token(mailbox,settings)
        db.commit()
    scheduler=None
    if settings.scheduler_enabled:
        scheduler=build_scheduler(sync_job,daily_summary_job,conversation_ai_review_job,daily_ai_connection_job);scheduler.start()
    app.state.scheduler=scheduler
    yield
    if scheduler:scheduler.shutdown(wait=False)
settings=get_settings();settings.validate_security();docs_enabled=settings.enable_api_docs and not settings.production
app=FastAPI(title=settings.app_name,version=settings.app_version,lifespan=lifespan,docs_url="/api/docs" if docs_enabled else None,redoc_url=None,openapi_url="/api/openapi.json" if docs_enabled else None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()])
cors_origins=list(dict.fromkeys(_origin_variants(settings.frontend_url)+_origin_variants(settings.dashboard_url)))
app.add_middleware(CORSMiddleware,allow_origins=cors_origins,allow_credentials=True,allow_methods=["*"],allow_headers=["*"]);app.include_router(router)
@app.middleware("http")
async def security_headers(request,call_next):
    request.state.request_id=secrets.token_hex(16)
    length=request.headers.get("content-length")
    if length and length.isdigit() and int(length)>settings.max_request_bytes:return JSONResponse({"detail":"Request body too large"},status_code=413)
    response=await call_next(request)
    response.headers["X-Request-ID"]=request.state.request_id
    response.headers["X-Content-Type-Options"]="nosniff";response.headers["X-Frame-Options"]="DENY";response.headers["Referrer-Policy"]="no-referrer";response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; font-src 'self'; form-action 'self'"
    if request.url.path.startswith("/api/") and request.url.path!="/api/health":response.headers["Cache-Control"]="no-store";response.headers["Pragma"]="no-cache"
    if settings.production:response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response
dist=Path(__file__).resolve().parents[2]/"frontend"/"dist"
def frontend_candidate(path:str)->Path:
    root=dist.resolve();candidate=(root/path).resolve()
    return candidate if path and candidate.is_relative_to(root) and candidate.is_file() else root/"index.html"
if dist.exists():
    app.mount("/assets",StaticFiles(directory=dist/"assets"),name="frontend-assets")
    @app.get("/{path:path}",include_in_schema=False)
    def frontend(path:str):
        return FileResponse(frontend_candidate(path))
