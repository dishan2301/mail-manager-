import asyncio
import base64
from email import message_from_bytes
from types import SimpleNamespace
from fastapi import Request
from fastapi import HTTPException
import pytest

from app.api import routes
from app.models.entities import Email
from app.services import gmail


class Response:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self, body): self.body = body
    def json(self): return self.body


class Client:
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def get(self, url, params=None, headers=None):
        if url.endswith("/profile"): return Response({"emailAddress": "owner@gmail.com", "historyId": "42"})
        if url.endswith("/messages"):
            folder = (params or {}).get("labelIds") or "ARCHIVE"
            return Response({"messages": [{"id": folder.lower()}]})
        message_id = url.rsplit("/", 1)[-1]
        labels = {"inbox": ["INBOX"], "sent": ["SENT"], "trash": ["TRASH"], "archive": []}[message_id]
        return Response({"id": message_id,"threadId": f"thread-{message_id}","internalDate": "1750000000000","labelIds": labels,"payload": {"headers": [{"name": "From", "value": "Customer <customer@example.com>"},{"name": "To", "value": "Owner <owner@gmail.com>"},{"name": "Subject", "value": "Support request"},{"name": "Message-ID", "value": f"<{message_id}@example.com>"}]}})


def test_gmail_initial_sync_reads_required_folders_and_normalizes_messages(monkeypatch):
    adapter = gmail.GmailDeltaSync(SimpleNamespace(max_sync_messages=100), "refresh-token")
    async def token(): adapter.access_token = "access-token"; return adapter.access_token
    adapter._token = token
    monkeypatch.setattr(gmail.httpx, "AsyncClient", lambda **_: Client())
    items, state = asyncio.run(adapter.sync_mailbox("owner@gmail.com"))
    assert state == "42"
    assert {item["_folder"] for item in items} == {"inbox", "sentitems", "deleteditems", "archive"}
    assert all(item["from"]["emailAddress"]["address"] == "customer@example.com" for item in items)
    assert all(item["toRecipients"][0]["emailAddress"]["address"] == "owner@gmail.com" for item in items)


def test_gmail_history_sync_fetches_changed_messages(monkeypatch):
    adapter = gmail.GmailDeltaSync(SimpleNamespace(max_sync_messages=100), "refresh-token")
    async def token(): adapter.access_token = "access-token"; return adapter.access_token
    async def get(_client, url, params=None):
        if url.endswith("/history"): return {"history": [{"messagesAdded": [{"message": {"id": "changed"}}]}]}
        return {"emailAddress": "owner@gmail.com", "historyId": "43"}
    async def message(_client, message_id): return {"id": message_id, "_folder": "inbox"}
    adapter._token = token; adapter._get = get; adapter._message = message
    monkeypatch.setattr(gmail.httpx, "AsyncClient", lambda **_: Client())
    items, state = asyncio.run(adapter.sync_mailbox("owner@gmail.com", "42"))
    assert items == [{"id": "changed", "_folder": "inbox"}]
    assert state == "43"


def test_gmail_message_content_prefers_nested_plain_text(monkeypatch):
    adapter = gmail.GmailDeltaSync(SimpleNamespace(), "refresh-token")
    encoded = base64.urlsafe_b64encode(b"Full customer request").decode().rstrip("=")
    async def get(_client, url, params=None):
        assert params == {"format": "full"}
        return {"payload": {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"data": encoded}},
            {"mimeType": "text/html", "filename": "", "body": {"data": "PGI-SFRNTDwvYj4"}},
        ]}}
    adapter._get = get
    monkeypatch.setattr(gmail.httpx, "AsyncClient", lambda **_: Client())
    assert asyncio.run(adapter.message_content("owner@gmail.com", "message-id")) == "Full customer request"


def test_gmail_send_reply_uses_existing_thread_and_reply_headers(monkeypatch):
    class SendResponse:
        status_code=200
    class SendClient(Client):
        async def post(self,url,json,headers):
            assert url.endswith("/messages/send")
            assert headers["Authorization"]=="Bearer access-token"
            self.payload=json
            return SendResponse()
    adapter=gmail.GmailDeltaSync(SimpleNamespace(),"refresh-token");adapter.access_token="access-token";client=SendClient()
    monkeypatch.setattr(gmail.httpx,"AsyncClient",lambda **_:client)
    asyncio.run(adapter.send_reply("owner@gmail.com","message-id","customer@example.com","Re: Help","Thanks for reaching out.","<original@example.com>","<older@example.com>","thread-id"))
    raw=base64.urlsafe_b64decode(client.payload["raw"]+"="*(-len(client.payload["raw"])%4))
    message=message_from_bytes(raw)
    assert client.payload["threadId"]=="thread-id"
    assert message["From"]=="owner@gmail.com" and message["To"]=="customer@example.com"
    assert message["In-Reply-To"]=="<original@example.com>"
    assert message["References"]=="<older@example.com> <original@example.com>"
    assert message.get_payload(decode=True).decode().strip()=="Thanks for reaching out."


def test_legacy_gmail_read_scope_is_upgraded_for_reply_consent():
    settings=SimpleNamespace(gmail_scopes="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email")
    assert "https://www.googleapis.com/auth/gmail.send" in gmail.gmail_scopes(settings)


def test_send_reply_route_targets_original_sender_and_marks_message_replied(monkeypatch):
    from datetime import datetime,timedelta,timezone
    from app.models.entities import SLATier
    mailbox=SimpleNamespace(provider="gmail",address="support@gmail.com",timezone="UTC")
    email=SimpleNamespace(id=7,mailbox_id=1,mailbox=mailbox,folder="inbox",sender="customer@example.com",subject="Help",message_id="provider-id",internet_message_id="<original@example.com>",references=None,conversation_id="thread-id",status=None,replied_at=None,received_time=datetime.now(timezone.utc)-timedelta(hours=2))
    class DB:
        def __init__(self):self.events=[];self.commits=0
        def get(self,model,key):return email if model is Email and key==7 else None
        def scalar(self,statement):return None
        def scalars(self,statement):return [SimpleNamespace(tier=tier,threshold_hours=hours,business_hours_only=False) for tier,hours in ((SLATier.WARNING,4),(SLATier.OVERDUE,8),(SLATier.CRITICAL,24))]
        def add(self,row):self.events.append(row)
        def commit(self):self.commits+=1
    class Strategy:
        async def send_reply(self,*args):self.args=args
    strategy=Strategy();db=DB();request=Request({"type":"http","method":"POST","path":"/api/emails/7/reply","headers":[],"client":("127.0.0.1",1)})
    monkeypatch.setattr(routes,"require_email_scope",lambda *_:email)
    monkeypatch.setattr(routes,"get_settings",lambda:SimpleNamespace())
    monkeypatch.setattr(routes,"_email_strategy",lambda *_:(strategy,None))
    monkeypatch.setattr(routes,"audit",lambda *_args,**_kwargs:None)
    result=asyncio.run(routes.send_email_reply(7,routes.ReplyInput(body="Thank you"),request,{"user_id":1,"role":"admin"},db))
    assert strategy.args==("support@gmail.com","provider-id","customer@example.com","Re: Help","Thank you","<original@example.com>",None,"thread-id")
    assert result["sent"] is True and email.status.value=="replied"
    assert email.replied_at.tzinfo==timezone.utc and db.commits==1
    assert 2<=email.pending_hours<2.01 and email.sla_tier==SLATier.HEALTHY


def test_outlook_send_scope_failure_returns_reconnect_guidance(monkeypatch):
    mailbox=SimpleNamespace(provider="microsoft",address="support@example.com")
    email=SimpleNamespace(id=8,mailbox_id=2,mailbox=mailbox,folder="inbox",sender="customer@example.com",subject="Help",message_id="provider-id",internet_message_id=None,references=None,conversation_id=None,status=None,replied_at=None)
    class DB:
        def get(self,model,key):return email if model is Email and key==8 else None
        def add(self,row):pass
        def commit(self):pass
    class Strategy:
        async def send_reply(self,*_):raise RuntimeError("Delegated Graph token refresh failed: AADSTS70000 unauthorized or expired scope")
    request=Request({"type":"http","method":"POST","path":"/api/emails/8/reply","headers":[],"client":("127.0.0.1",1)})
    monkeypatch.setattr(routes,"require_email_scope",lambda *_:email)
    monkeypatch.setattr(routes,"get_settings",lambda:SimpleNamespace())
    monkeypatch.setattr(routes,"_email_strategy",lambda *_:(Strategy(),"refresh-token"))
    monkeypatch.setattr(routes,"_save_refreshed_mailbox_token",lambda *_:None)
    monkeypatch.setattr(routes,"audit",lambda *_args,**_kwargs:None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.send_email_reply(8,routes.ReplyInput(body="Thank you"),request,{"user_id":1,"role":"admin"},DB()))
    assert error.value.status_code==409 and "approve Mail.Send" in error.value.detail


def test_admin_email_content_route_returns_provider_body_and_audits(monkeypatch):
    mailbox=SimpleNamespace(provider="gmail",address="owner@gmail.com")
    email=SimpleNamespace(id=7,mailbox_id=1,mailbox=mailbox,message_id="provider-message")
    class DB:
        def __init__(self):self.events=[];self.commits=0
        def get(self,model,key):return email if model is Email and key==7 else None
        def add(self,row):self.events.append(row)
        def commit(self):self.commits+=1
    class Strategy:
        def __init__(self,settings,token):assert token=="refresh-token"
        async def message_content(self,address,message_id):
            assert (address,message_id)==("owner@gmail.com","provider-message")
            return "Full customer request"
    db=DB();request=Request({"type":"http","method":"GET","path":"/api/emails/7/content","headers":[],"client":("127.0.0.1",1)})
    monkeypatch.setattr(routes,"get_mailbox_token",lambda *_:"refresh-token")
    monkeypatch.setattr(routes,"GmailDeltaSync",Strategy)
    result=asyncio.run(routes.email_content(7,request,{"user_id":1,"role":"admin"},db))
    assert result=={"content":"Full customer request","content_type":"text/plain"}
    assert db.commits==1 and db.events[-1].action=="email.content.read" and db.events[-1].outcome=="success"
