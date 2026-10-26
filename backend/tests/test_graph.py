import asyncio,json
import pytest
from pathlib import Path
from app.core.config import Settings
from app.services import graph

class Response:
    status_code=200;headers={}
    def __init__(self,url):self.url=url
    def raise_for_status(self):pass
    def json(self):
        folder=next(x for x in graph.FOLDERS if f"/{x}/" in self.url)
        return {"value":[{"id":folder}],"@odata.deltaLink":f"https://graph.microsoft.com/delta/{folder}"}
class Client:
    async def __aenter__(self):return self
    async def __aexit__(self,*_):pass
    async def get(self,url,headers):return Response(url)
class TokenApp:
    def acquire_token_silent(self,*_,**__):return {"access_token":"token"}

@pytest.mark.parametrize("adapter_type",[graph.GraphDeltaSync,graph.DelegatedGraphDeltaSync])
@pytest.mark.parametrize("resume",[False,True])
def test_large_mailbox_loads_all_pages_and_then_new_mail(monkeypatch,adapter_type,resume):
    class PageResponse:
        status_code=200;headers={}
        def __init__(self,url):self.url=url
        def raise_for_status(self):pass
        def json(self):
            folder=next(x for x in graph.FOLDERS if f"/{x}/" in self.url)
            resumed="page=2" in self.url or self.url.endswith("/done")
            ids=[102] if self.url.endswith("/done") else [101] if resumed else range(1,101)
            return {"value":[{"id":f"{folder}-{i}"} for i in ids],
                    "@odata.deltaLink" if resumed else "@odata.nextLink":f"https://graph.microsoft.com/{folder}/"+("done" if resumed else "?page=2")}
    class PageClient(Client):
        async def get(self,url,headers):
            assert headers["Prefer"]=="odata.maxpagesize=100"
            if "page=2" not in url and not url.endswith("/done"):
                assert "$orderby=receivedDateTime+desc" in url and "$top=100" in url
            return PageResponse(url)
    adapter=adapter_type.__new__(adapter_type);adapter.settings=Settings()
    async def token(force=False):return "token"
    adapter._token=token
    monkeypatch.setattr(graph.httpx,"AsyncClient",lambda **_:PageClient())
    saved_state=json.dumps({folder:f"https://graph.microsoft.com/{folder}/?page=2" for folder in graph.FOLDERS}) if resume else None
    first,state=asyncio.run(adapter.sync_mailbox("support@example.com",saved_state))
    assert len(first)==len(graph.FOLDERS)*(1 if resume else 101)
    assert all(cursor.endswith("/done") for cursor in json.loads(state).values())
    second,state=asyncio.run(adapter.sync_mailbox("support@example.com",state))
    assert len(second)==len(graph.FOLDERS)
    assert not {item["id"] for item in first}&{item["id"] for item in second}
    assert all(cursor.endswith("/done") for cursor in json.loads(state).values())

def test_graph_sync_reads_every_required_folder(monkeypatch):
    adapter=graph.GraphDeltaSync.__new__(graph.GraphDeltaSync);adapter.settings=Settings();adapter.app=TokenApp();monkeypatch.setattr(graph.httpx,"AsyncClient",lambda **_:Client())
    items,state=asyncio.run(adapter.sync_mailbox("support@example.com"));parsed=json.loads(state)
    assert {x["_folder"] for x in items}==set(graph.FOLDERS)
    assert set(parsed)==set(graph.FOLDERS)
def test_graph_certificate_credential():
    key=Path(__file__).parents[2]/"README.md"
    settings=Settings(azure_client_secret="",azure_client_certificate_path=str(key),azure_client_certificate_thumbprint="ABC123")
    credential=graph.GraphDeltaSync._credential(settings)
    assert credential["private_key"].startswith("# OEIS") and credential["thumbprint"]=="ABC123"

def test_graph_reacquires_once_on_401_and_honors_retry_after_on_429():
    class ScriptedResponse:
        def __init__(self,status,body=None,headers=None):self.status_code=status;self._body=body or {};self.headers=headers or {}
        def raise_for_status(self):
            if self.status_code>=400:raise RuntimeError(f"HTTP {self.status_code}")
        def json(self):return self._body
    class ScriptedClient:
        def __init__(self):self.responses=[ScriptedResponse(401),ScriptedResponse(429,headers={"Retry-After":"0"}),ScriptedResponse(200,{"value":[],"@odata.deltaLink":"https://graph.microsoft.com/delta/inbox"})];self.tokens=[]
        async def get(self,url,headers):self.tokens.append(headers["Authorization"]);return self.responses.pop(0)
    adapter=graph.GraphDeltaSync.__new__(graph.GraphDeltaSync);calls=[]
    async def token(force=False):calls.append(force);return "fresh-token"
    adapter._token=token;adapter.settings=Settings();client=ScriptedClient()
    items,delta=asyncio.run(adapter._folder(client,"support@example.com","inbox","https://graph.microsoft.com/start","expired-token"))
    assert items==[] and delta=="https://graph.microsoft.com/delta/inbox"
    assert calls==[True]
    assert client.tokens==["Bearer expired-token","Bearer fresh-token","Bearer fresh-token"]

def test_graph_message_content_requests_plain_text_and_encodes_message_id(monkeypatch):
    class ContentResponse:
        status_code=200;headers={}
        def json(self):return {"body":{"content":"Full customer request"}}
    class ContentClient:
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def get(self,url,headers):self.url=url;self.headers=headers;return ContentResponse()
    client=ContentClient();adapter=graph.GraphDeltaSync.__new__(graph.GraphDeltaSync);adapter.settings=Settings()
    async def token(force=False):return "token"
    adapter._token=token;monkeypatch.setattr(graph.httpx,"AsyncClient",lambda **_:client)
    content=asyncio.run(adapter.message_content("support@example.com","opaque/id+value="))
    assert content=="Full customer request"
    assert "/users/support@example.com/messages/opaque%2Fid%2Bvalue%3D" in client.url
    assert client.headers["Prefer"]=='outlook.body-content-type="text"'

def test_graph_reply_uses_provider_reply_action_and_encodes_message_id(monkeypatch):
    class ReplyResponse:
        status_code=202;headers={}
    class ReplyClient:
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def post(self,url,json,headers):
            self.url=url;self.payload=json;self.headers=headers;return ReplyResponse()
    client=ReplyClient();adapter=graph.GraphDeltaSync.__new__(graph.GraphDeltaSync);adapter.settings=Settings()
    async def token(force=False):return "token"
    adapter._token=token;monkeypatch.setattr(graph.httpx,"AsyncClient",lambda **_:client)
    asyncio.run(adapter.send_reply("support@example.com","opaque/id+value=","customer@example.com","Re: Help","Thanks"))
    assert client.url.endswith("/users/support@example.com/messages/opaque%2Fid%2Bvalue%3D/reply")
    assert client.payload=={"comment":"Thanks"} and client.headers["Authorization"]=="Bearer token"

def test_graph_report_delivery_uses_send_mail(monkeypatch):
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def post(self,url,json,headers):
            self.url=url;self.payload=json;self.headers=headers
            return type("Response",(),{"status_code":202})()
    client=Client();adapter=graph.GraphDeltaSync.__new__(graph.GraphDeltaSync);adapter.settings=Settings()
    async def token():return "token"
    adapter._send_token=token
    monkeypatch.setattr(graph.httpx,"AsyncClient",lambda **_:client)
    asyncio.run(adapter.send_html("support@example.com","admin@example.com","Daily summary","<b>Report</b>"))
    assert client.url.endswith("/users/support@example.com/sendMail")
    assert client.payload["message"]["toRecipients"][0]["emailAddress"]["address"]=="admin@example.com"
    assert client.payload["message"]["body"]=={"contentType":"HTML","content":"<b>Report</b>"}
    assert client.headers["Authorization"]=="Bearer token"

def test_legacy_graph_read_scope_is_upgraded_for_reply_consent():
    settings=Settings(graph_delegated_scopes="Mail.Read offline_access User.Read")
    assert graph.delegated_scopes(settings)==["Mail.Read","User.Read"]
    assert graph.delegated_auth_code_scopes(settings)==["Mail.Read","User.Read","Mail.Send"]

def test_delegated_refresh_requests_send_scope_only_for_reply():
    class DelegatedTokenApp:
        def __init__(self):self.scopes=[]
        def acquire_token_by_refresh_token(self,refresh_token,scopes):
            self.scopes.append(scopes)
            return {"access_token":"token","refresh_token":"rotated-token"}
    adapter=graph.DelegatedGraphDeltaSync.__new__(graph.DelegatedGraphDeltaSync)
    adapter.settings=Settings(graph_delegated_scopes="Mail.Read Mail.Send offline_access User.Read")
    adapter.refresh_token="refresh-token";adapter.latest_refresh_token="refresh-token";adapter.app=DelegatedTokenApp()
    assert adapter._token_sync()=="token"
    assert adapter._token_sync(send=True)=="token"
    assert adapter.app.scopes==[["Mail.Read","User.Read"],["Mail.Read","User.Read","Mail.Send"]]
