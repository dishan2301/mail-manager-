from fastapi.testclient import TestClient
import os
from app.core.database import SessionLocal
from app.main import app
from app.models.entities import OAuthTransaction,Role,User
from app.core.security import hash_password
from sqlalchemy import select
from app.core.config import get_settings
from app.api import routes
from datetime import datetime,timezone

def test_audit_timestamps_mark_sqlite_values_as_utc():
    value=routes._utc_timestamp(datetime(2026,8,20,12,39,17))
    assert value.tzinfo==timezone.utc and value.isoformat()=="2026-08-20T12:39:17+00:00"

def test_manager_is_denied_admin_mailbox_mutation():
    with TestClient(app) as client:
        with SessionLocal() as db:
            manager=db.scalar(select(User).where(User.email=="security-manager@example.com"))
            if not manager:
                manager=User(email="security-manager@example.com",name="Security Manager",password_hash=hash_password("Manager-Security-123!"),role=Role.MANAGER,active=True);db.add(manager);db.commit();db.refresh(manager)
        token=client.post("/api/auth/login",data={"username":"security-manager@example.com","password":"Manager-Security-123!"}).json()["access_token"]
        response=client.post("/api/mailboxes",json={"address":"support@example.com","display_name":"Support"},headers={"Authorization":f"Bearer {token}"})
        assert response.status_code==403
        assert response.json()=={"detail":"Forbidden"}
        mailbox_list=client.get("/api/mailboxes",headers={"Authorization":f"Bearer {token}"})
        assert mailbox_list.status_code==403
        assert mailbox_list.json()=={"detail":"Forbidden"}
        options=client.get("/api/mailbox-options",headers={"Authorization":f"Bearer {token}"})
        assert options.status_code==200
        assert all(set(row)=={"id","address","display_name"} for row in options.json())
        readiness=client.get("/api/system/readiness",headers={"Authorization":f"Bearer {token}"})
        assert readiness.status_code==200
        assert "operational" in readiness.json() and "graph_configured" in readiness.json()
def test_unauthenticated_pending_is_denied():
    with TestClient(app) as client:assert client.get("/api/emails/pending").status_code==401

def test_unauthenticated_email_content_is_denied():
    with TestClient(app) as client:assert client.get("/api/emails/1/content").status_code==401

def test_unauthenticated_email_reply_and_ai_assistance_are_denied():
    with TestClient(app) as client:
        assert client.post("/api/emails/1/reply",json={"body":"Reply"}).status_code==401
        assert client.post("/api/emails/1/rewrite",json={"mode":"draft","body":""}).status_code==401

def test_admin_login_and_report_exports(monkeypatch,tmp_path):
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"})
        assert login.status_code==200
        headers={"Authorization":f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/reports/daily/export?dimension=mailbox&format=xlsx",headers=headers).status_code==200
        assert client.get("/api/reports/daily/export?dimension=mailbox&format=pdf",headers=headers).headers["content-type"]=="application/pdf"
        assert client.post("/api/reports/daily/send",headers=headers).status_code==503
        assert client.post("/api/sync/trigger",headers=headers).status_code==409
        setup=client.get("/api/system/graph-setup?mailbox=support@example.com",headers=headers)
        assert setup.status_code==200
        body=setup.json()
        assert body["graph_configured"] is False
        assert "Microsoft Graph application permissions Mail.Read and Mail.Send" in body["required_permission"]
        assert "support@example.com" in body["exchange_policy_commands"]
        assert "AZURE_CLIENT_ID" in body["env_template"]
        assert "az ad app create" in body["azure_cli_commands"]
        assert "MAIL_READ_ROLE_ID" in body["azure_cli_commands"]
        assert client.post("/api/system/graph-setup",headers=headers,json={"azure_tenant_id":"tenant-1","azure_client_id":"client-1","azure_client_secret":"secret#1","graph_scope":"https://graph.microsoft.com/.default"}).status_code==405
        assert client.post("/api/system/graph-config",headers=headers,json={"azure_tenant_id":"tenant-1","azure_client_id":"client-1","azure_client_secret":"secret#1","graph_scope":"https://graph.microsoft.com/.default"}).status_code in {404,405}
        for key in ("AZURE_TENANT_ID","AZURE_CLIENT_ID","AZURE_CLIENT_SECRET","GRAPH_SCOPE"):os.environ.pop(key,None)
    get_settings.cache_clear()
def test_manager_cannot_open_graph_setup_pipeline():
    with TestClient(app) as client:
        with SessionLocal() as db:
            manager=db.scalar(select(User).where(User.email=="graph-manager@example.com"))
            if not manager:
                manager=User(email="graph-manager@example.com",name="Graph Manager",password_hash=hash_password("Manager-Graph-123!"),role=Role.MANAGER,active=True);db.add(manager);db.commit();db.refresh(manager)
        token=client.post("/api/auth/login",data={"username":"graph-manager@example.com","password":"Manager-Graph-123!"}).json()["access_token"]
        assert client.get("/api/system/graph-setup",headers={"Authorization":f"Bearer {token}"}).status_code==403
def test_graph_check_reports_missing_credentials(monkeypatch):
    for key in ("AZURE_TENANT_ID","AZURE_CLIENT_ID","AZURE_CLIENT_SECRET","AZURE_CLIENT_CERTIFICATE_PATH"):monkeypatch.delenv(key,raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        response=client.post("/api/system/graph-check",headers={"Authorization":f"Bearer {login['access_token']}"},json={})
        assert response.status_code==503
        assert response.json()["detail"]=="Microsoft Graph credentials are not configured"
def test_graph_check_can_verify_credentials_and_mailbox(monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID","tenant-1");monkeypatch.setenv("AZURE_CLIENT_ID","client-1");monkeypatch.setenv("AZURE_CLIENT_SECRET","secret-1");get_settings.cache_clear()
    class Graph:
        def __init__(self,settings):self.settings=settings
        async def _token(self,force=False):return "token"
        async def sync_mailbox(self,address):return [],"{}"
    monkeypatch.setattr(routes,"GraphDeltaSync",Graph)
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        response=client.post("/api/system/graph-check",headers={"Authorization":f"Bearer {login['access_token']}"},json={"mailbox":"support@example.com"})
        assert response.status_code==200
        assert response.json()=={"ok":True,"mailbox_checked":True}
    get_settings.cache_clear()
def test_admin_can_add_gmail_mailbox_and_oauth_requires_google_config(monkeypatch):
    from uuid import uuid4
    monkeypatch.delenv("GOOGLE_CLIENT_ID",raising=False);monkeypatch.delenv("GOOGLE_CLIENT_SECRET",raising=False);get_settings.cache_clear()
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json();headers={"Authorization":f"Bearer {login['access_token']}"}
        address=f"gmail-{uuid4().hex}@gmail.com"
        created=client.post("/api/mailboxes",headers=headers,json={"address":address,"display_name":"Gmail support","provider":"gmail","timezone":"Asia/Kolkata"})
        assert created.status_code==201 and created.json()["provider"]=="gmail" and created.json()["connected"] is False
        started=client.post(f"/api/mailboxes/{created.json()['id']}/gmail/oauth/start",headers=headers)
        assert started.status_code==503 and "Google OAuth" in started.json()["detail"]
    get_settings.cache_clear()
def test_gmail_oauth_state_is_persisted_outside_process_memory(monkeypatch):
    from urllib.parse import parse_qs,urlparse
    monkeypatch.setenv("GOOGLE_CLIENT_ID","client-id");monkeypatch.setenv("GOOGLE_CLIENT_SECRET","client-secret");get_settings.cache_clear()
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json();headers={"Authorization":f"Bearer {login['access_token']}"}
        from uuid import uuid4
        created=client.post("/api/mailboxes",headers=headers,json={"address":f"state-{uuid4().hex}@gmail.com","display_name":"State test","provider":"gmail","timezone":"UTC"}).json()
        started=client.post(f"/api/mailboxes/{created['id']}/gmail/oauth/start",headers=headers)
        assert started.status_code==200
        state=parse_qs(urlparse(started.json()["auth_url"]).query)["state"][0]
        from hashlib import sha256
        with SessionLocal() as db:assert db.scalar(select(OAuthTransaction).where(OAuthTransaction.state_hash==sha256(state.encode()).hexdigest()))
    monkeypatch.delenv("GOOGLE_CLIENT_ID",raising=False);monkeypatch.delenv("GOOGLE_CLIENT_SECRET",raising=False);get_settings.cache_clear()
def test_disabled_user_cannot_use_existing_access_or_refresh_token():
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        with SessionLocal() as db:
            admin=db.scalar(select(User).where(User.email=="admin@oeis.local"));admin.active=False;db.commit()
        try:
            assert client.get("/api/dashboard/kpis",headers={"Authorization":f"Bearer {login['access_token']}"}).status_code==401
            assert client.post("/api/auth/refresh").status_code==401
        finally:
            with SessionLocal() as db:
                admin=db.scalar(select(User).where(User.email=="admin@oeis.local"));admin.active=True;db.commit()
def test_admin_can_update_employee_and_user_administration_records():
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        headers={"Authorization":f"Bearer {login['access_token']}"}
        employee=client.post("/api/employees",json={"name":"Editable Employee","email":"editable-employee@indianinfotech.org","active":True},headers=headers)
        if employee.status_code==409:
            employee_id=next(row["id"] for row in client.get("/api/employees",headers=headers).json() if row["email"]=="editable-employee@indianinfotech.org")
        else:employee_id=employee.json()["id"]
        updated=client.patch(f"/api/employees/{employee_id}",json={"name":"Updated Employee","active":False},headers=headers)
        assert updated.status_code==200 and updated.json()["name"]=="Updated Employee" and updated.json()["active"] is False
        user=client.post("/api/users",json={"name":"Editable Manager","email":"editable-manager@example.com","password":"Editable-Manager-123!","role":"manager","active":True},headers=headers)
        if user.status_code==409:
            user_id=next(row["id"] for row in client.get("/api/users",headers=headers).json() if row["email"]=="editable-manager@example.com")
        else:user_id=user.json()["id"]
        updated=client.patch(f"/api/users/{user_id}",json={"role":"admin","active":False},headers=headers)
        assert updated.status_code==200 and updated.json()["role"]=="admin" and updated.json()["active"] is False

def test_admin_can_set_own_email_and_password():
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"})
        headers={"Authorization":f"Bearer {login.json()['access_token']}"}
        created=client.post("/api/users",headers=headers,json={"name":"Self Edit Admin","email":"self-edit-before@example.com","password":"Initial-Self-Edit-123!","role":"admin"})
        user_id=created.json()["id"]
        own_login=client.post("/api/auth/login",data={"username":"self-edit-before@example.com","password":"Initial-Self-Edit-123!"})
        own_headers={"Authorization":f"Bearer {own_login.json()['access_token']}"}
        changed=client.patch(f"/api/users/{user_id}",headers=own_headers,json={"email":"self-edit-after@example.com","password":"New-Self-Edit-456!"})
        assert changed.status_code==200 and changed.json()["reauthenticate"] is True
        assert client.get("/api/users",headers=own_headers).status_code==401
        assert client.post("/api/auth/login",data={"username":"self-edit-before@example.com","password":"Initial-Self-Edit-123!"}).status_code==401
        assert client.post("/api/auth/login",data={"username":"self-edit-after@example.com","password":"New-Self-Edit-456!"}).status_code==200
        assert client.patch(f"/api/users/{user_id}",headers=headers,json={"email":"admin@oeis.local"}).status_code==409

def test_adding_existing_employee_updates_instead_of_conflict():
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        headers={"Authorization":f"Bearer {login['access_token']}"}
        first=client.post("/api/employees",json={"name":"Zzz First Name","email":"duplicate-employee@indianinfotech.org","active":False},headers=headers)
        assert first.status_code==201
        second=client.post("/api/employees",json={"name":"Zzz Second Name","email":"DUPLICATE-EMPLOYEE@indianinfotech.org","active":True},headers=headers)
        assert second.status_code==201
        body=second.json()
        assert body["id"]==first.json()["id"]
        assert body["name"]=="Zzz Second Name"
        assert body["email"]=="duplicate-employee@indianinfotech.org"
        assert body["active"] is True

def test_admin_can_manage_dynamic_ui_content_and_public_reads_active_rows():
    with TestClient(app) as client:
        login=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"}).json()
        headers={"Authorization":f"Bearer {login['access_token']}"}
        created=client.post("/api/ui-content/manage",json={"source":"test.dynamic.copy","text":"Initial dynamic copy","active":True},headers=headers)
        assert created.status_code==201
        content_id=created.json()["id"]
        public=client.get("/api/ui-content").json()["items"]
        assert {"source":"test.dynamic.copy","text":"Initial dynamic copy"} in public
        updated=client.patch(f"/api/ui-content/manage/{content_id}",json={"text":"Updated dynamic copy"},headers=headers)
        assert updated.status_code==200 and updated.json()["text"]=="Updated dynamic copy"
        disabled=client.patch(f"/api/ui-content/manage/{content_id}",json={"active":False},headers=headers)
        assert disabled.status_code==200 and disabled.json()["active"] is False
        public=client.get("/api/ui-content").json()["items"]
        assert {"source":"test.dynamic.copy","text":"Updated dynamic copy"} not in public
