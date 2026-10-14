from datetime import datetime,timedelta,timezone
import hashlib
import hmac
from urllib.parse import urlparse

from fastapi import HTTPException,Request,status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import LoginThrottle,SecurityAuditEvent


def utc(value:datetime|None)->datetime|None:
    if value is None:return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def fingerprint(value:str)->str:
    return hmac.new(get_settings().jwt_secret.encode(),value.encode(),hashlib.sha256).hexdigest()


def request_source(request:Request)->str:
    return request.client.host if request.client else "unknown"
def _origin_variants(value:str)->set[str]:
    parsed=urlparse(value)
    if not parsed.scheme or not parsed.netloc:return set()
    hosts={parsed.hostname or ""}
    if parsed.hostname in {"localhost","127.0.0.1","0.0.0.0"}:hosts.update({"localhost","127.0.0.1","0.0.0.0"})
    port=f":{parsed.port}" if parsed.port else ""
    return {f"{parsed.scheme}://{host}{port}" for host in hosts if host}


def audit(db:Session,request:Request|None,action:str,outcome:str,actor_user_id:int|None=None,object_type:str|None=None,object_id:str|int|None=None,details:dict|None=None)->None:
    safe={str(key)[:80]:value for key,value in (details or {}).items() if isinstance(value,(str,int,float,bool)) or value is None}
    db.add(SecurityAuditEvent(actor_user_id=actor_user_id,action=action[:80],object_type=object_type[:80] if object_type else None,object_id=str(object_id)[:128] if object_id is not None else None,outcome=outcome[:30],source_hash=fingerprint(request_source(request)) if request else None,request_id=getattr(request.state,"request_id",None) if request else None,details=safe,created_at=datetime.now(timezone.utc)))


def validate_cookie_origin(request:Request)->None:
    if request.headers.get("sec-fetch-site","").lower()=="cross-site":raise HTTPException(status.HTTP_403_FORBIDDEN,"Cross-site request rejected")
    if not get_settings().production:return
    origin=request.headers.get("origin")
    if not origin:return
    settings=get_settings();allowed=set().union(*(_origin_variants(value) for value in (settings.frontend_url,settings.dashboard_url)))
    if not settings.production:
        parsed_origin=urlparse(origin)
        if parsed_origin.scheme == "http" and parsed_origin.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return
        for port in (5173, 8080, 10000):
            allowed.update({f"http://localhost:{port}", f"http://127.0.0.1:{port}"})
    if origin.rstrip("/") not in allowed:raise HTTPException(status.HTTP_403_FORBIDDEN,"Request origin rejected")


def _throttle_keys(email:str,request:Request)->list[str]:
    return [fingerprint(f"account:{email.strip().lower()}"),fingerprint(f"source:{request_source(request)}")]


def check_login_allowed(db:Session,email:str,request:Request)->None:
    now=datetime.now(timezone.utc);blocked=[]
    for key in _throttle_keys(email,request):
        row=db.get(LoginThrottle,key)
        if row and utc(row.blocked_until) and utc(row.blocked_until)>now:blocked.append(int((utc(row.blocked_until)-now).total_seconds())+1)
    if blocked:raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,"Too many authentication attempts",headers={"Retry-After":str(max(blocked))})


def record_login_failure(db:Session,email:str,request:Request)->None:
    settings=get_settings();now=datetime.now(timezone.utc);window=timedelta(minutes=settings.login_window_minutes)
    for key in _throttle_keys(email,request):
        row=db.get(LoginThrottle,key)
        if not row or utc(row.window_started_at)+window<=now:
            row=LoginThrottle(key_hash=key,failures=0,window_started_at=now);db.add(row)
        row.failures+=1;delay=timedelta(seconds=min(2**max(row.failures-1,0),60))
        row.blocked_until=max(now+delay,utc(row.window_started_at)+window) if row.failures>=settings.login_max_failures else now+delay


def clear_login_failures(db:Session,email:str,request:Request)->None:
    for key in _throttle_keys(email,request):
        row=db.get(LoginThrottle,key)
        if row:db.delete(row)
