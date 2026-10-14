from abc import ABC,abstractmethod
import asyncio,json
from pathlib import Path
import re
from urllib.parse import quote,urlsplit
import httpx,msal
from app.core.config import Settings

FOLDERS=("inbox","sentitems","deleteditems","archive")
RESERVED_SCOPES={"openid","profile","offline_access"}
ALLOWED_DELEGATED_SCOPES={"Mail.Read","Mail.Send","User.Read"}
PERSONAL_MAIL_DOMAINS={"outlook.com","hotmail.com","live.com","msn.com"}
def delegated_authority_tenant(address:str,settings:Settings)->str:
    domain=address.rsplit("@",1)[-1].lower()
    return "consumers" if domain in PERSONAL_MAIL_DOMAINS else settings.azure_tenant_id.strip() or "common"
def delegated_graph_application(settings:Settings,authority_tenant:str):
    if not settings.azure_client_secret:raise RuntimeError("AZURE_CLIENT_SECRET is required for Outlook web login")
    return msal.ConfidentialClientApplication(settings.azure_client_id,authority=f"https://login.microsoftonline.com/{authority_tenant}",client_credential=settings.azure_client_secret)
def delegated_scopes(settings:Settings)->list[str]:
    scopes=[scope for scope in settings.graph_delegated_scopes.split() if scope not in RESERVED_SCOPES]
    if not scopes or not set(scopes)<=ALLOWED_DELEGATED_SCOPES or "Mail.Read" not in scopes:raise RuntimeError("Microsoft delegated scopes exceed OEIS allowlist")
    return [scope for scope in scopes if scope!="Mail.Send"]
def delegated_auth_code_scopes(settings:Settings)->list[str]:
    # MSAL adds openid, profile, and offline_access itself. Passing them here
    # raises a reserved-scope ValueError before Microsoft login can start.
    scopes=delegated_scopes(settings)
    scopes.append("Mail.Send")
    return scopes
def validate_graph_url(url:str,settings:Settings)->str:
    parsed=urlsplit(url);allowed={host.strip().lower() for host in settings.graph_allowed_hosts.split(",") if host.strip()}
    if parsed.scheme!="https" or (parsed.hostname or "").lower() not in allowed or parsed.port not in (None,443) or parsed.username or parsed.password:raise RuntimeError("Graph continuation URL was rejected")
    return url
def _graph_error(response:httpx.Response)->str:
    try:
        code=str(response.json().get("error",{}).get("code","")).strip()
        if code and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",code):return f"Graph request failed ({response.status_code}, {code})"
    except ValueError:
        pass
    return f"Graph request failed ({response.status_code})"
def _token_error(result:dict,prefix:str)->str:
    code=str(result.get("error","")).strip()
    detail=str(result.get("error_description","")).strip().replace("\r"," ").replace("\n"," ")
    if detail:
        return f"{prefix}: {detail[:300]}"
    if code:
        return f"{prefix}: {code[:80]}"
    return prefix
def _retry_delay(value:str|None,attempt:int)->int:
    try:return max(1,min(int(value or 2**attempt),30))
    except (TypeError,ValueError):return min(2**attempt,30)
def _request_error(exc:Exception,prefix:str)->RuntimeError:
    return RuntimeError(f"{prefix}: {str(exc).strip() or type(exc).__name__}")
async def _with_request_retry(action,prefix:str,attempts:int=4):
    for attempt in range(attempts):
        try:
            return await action()
        except httpx.RequestError as exc:
            if attempt>=attempts-1:raise _request_error(exc,prefix) from exc
            await asyncio.sleep(_retry_delay(None,attempt))
def _with_token_retry(action,prefix:str,attempts:int=4):
    for attempt in range(attempts):
        try:
            return action()
        except Exception as exc:
            message=str(exc)
            transient=isinstance(exc,(ConnectionError,TimeoutError)) or "NameResolutionError" in message or "HTTPSConnectionPool" in message or "temporar" in message.lower()
            if not transient or attempt>=attempts-1:raise
            import time;time.sleep(_retry_delay(None,attempt))

class IMailSyncStrategy(ABC):
    @abstractmethod
    async def sync_mailbox(self,address:str,delta_state:str|None=None)->tuple[list[dict],str]:...
class GraphDeltaSync(IMailSyncStrategy):
    def __init__(self,settings:Settings):
        self.settings=settings
        if settings.graph_scope!="https://graph.microsoft.com/.default":raise RuntimeError("GRAPH_SCOPE must use Microsoft Graph .default")
        credential=self._credential(settings)
        self.app=msal.ConfidentialClientApplication(settings.azure_client_id,authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",client_credential=credential)
    @staticmethod
    def _credential(settings:Settings):
        if settings.azure_client_certificate_path:
            if not settings.azure_client_certificate_thumbprint:raise ValueError("AZURE_CLIENT_CERTIFICATE_THUMBPRINT is required with a certificate")
            private_key=Path(settings.azure_client_certificate_path).read_text(encoding="utf-8")
            return {"private_key":private_key,"thumbprint":settings.azure_client_certificate_thumbprint}
        if not settings.azure_client_secret:raise ValueError("Configure an Azure client secret or certificate")
        return settings.azure_client_secret
    def _token_sync(self,force=False):
        scopes=[self.settings.graph_scope]
        def acquire():
            result=None if force else self.app.acquire_token_silent(scopes,account=None)
            return result or self.app.acquire_token_for_client(scopes=scopes)
        result=_with_token_retry(acquire,"Graph token acquisition failed")
        if "access_token" not in result:raise RuntimeError(_token_error(result,"Graph token acquisition failed"))
        return result["access_token"]
    async def _token(self,force=False):return await asyncio.to_thread(self._token_sync,force)
    async def _send_token(self):return await self._token()
    def _message_url(self,address:str,message_id:str)->str:
        return f"https://graph.microsoft.com/v1.0/users/{quote(address,safe='@')}/messages/{quote(message_id,safe='')}?$select=body"
    async def message_content(self,address:str,message_id:str)->str:
        token=await self._token();refreshed=False;attempts=0;url=validate_graph_url(self._message_url(address,message_id),self.settings)
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            while True:
                response=await _with_request_retry(lambda: client.get(url,headers={"Authorization":f"Bearer {token}","Prefer":'outlook.body-content-type="text"'}),"Graph message request failed")
                if response.status_code==401 and not refreshed:token=await self._token(True);refreshed=True;continue
                if response.status_code==429 and attempts<4:await asyncio.sleep(_retry_delay(response.headers.get("Retry-After"),attempts));attempts+=1;continue
                if response.status_code>=400:raise RuntimeError(_graph_error(response))
                return str(response.json().get("body",{}).get("content") or "")[:1_000_000]
    async def send_reply(self,address:str,message_id:str,recipient:str,subject:str,body:str,internet_message_id:str|None=None,references:str|None=None,conversation_id:str|None=None)->None:
        del recipient,subject,internet_message_id,references,conversation_id
        token=await self._send_token();url=validate_graph_url(self._reply_url(address,message_id),self.settings)
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            response=await client.post(url,json={"comment":body},headers={"Authorization":f"Bearer {token}"})
        if response.status_code>=400:raise RuntimeError(_graph_error(response))
    async def send_html(self,address:str,recipient:str,subject:str,html:str)->None:
        token=await self._send_token()
        url=validate_graph_url(self._send_mail_url(address),self.settings)
        payload={"message":{"subject":subject,"body":{"contentType":"HTML","content":html},"toRecipients":[{"emailAddress":{"address":recipient}}]},"saveToSentItems":True}
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            response=await client.post(url,json=payload,headers={"Authorization":f"Bearer {token}"})
        if response.status_code>=400:raise RuntimeError(_graph_error(response))
    def _send_mail_url(self,address:str)->str:
        return f"https://graph.microsoft.com/v1.0/users/{quote(address,safe='@')}/sendMail"
    def _reply_url(self,address:str,message_id:str)->str:
        return f"https://graph.microsoft.com/v1.0/users/{quote(address,safe='@')}/messages/{quote(message_id,safe='')}/reply"
    async def _folder(self,client,address,folder,url,token):
        fields="id,conversationId,internetMessageId,conversationIndex,subject,from,toRecipients,receivedDateTime,sentDateTime,parentFolderId,internetMessageHeaders,categories";url=url or f"https://graph.microsoft.com/v1.0/users/{quote(address,safe='@')}/mailFolders/{folder}/messages/delta?$select={fields}";items=[];refreshed=False;attempts=0;delta=url
        while url:
            response=await _with_request_retry(lambda: client.get(validate_graph_url(url,self.settings),headers={"Authorization":f"Bearer {token}"}),"Graph request failed")
            if response.status_code==401 and not refreshed:token=await self._token(True);refreshed=True;continue
            if response.status_code==429 and attempts<4:await asyncio.sleep(_retry_delay(response.headers.get("Retry-After"),attempts));attempts+=1;continue
            if response.status_code>=400:raise RuntimeError(_graph_error(response))
            response.raise_for_status();body=response.json()
            for item in body.get("value",[]):
                item["_folder"]=folder;items.append(item)
                if len(items)>self.settings.max_sync_messages:raise RuntimeError("Graph sync exceeds configured message limit")
            url=body.get("@odata.nextLink");delta=body.get("@odata.deltaLink",delta)
            if url:validate_graph_url(url,self.settings)
            if delta:validate_graph_url(delta,self.settings)
        return items,delta
    async def sync_mailbox(self,address,delta_state=None):
        state=json.loads(delta_state) if delta_state else {};token=await self._token();all_items=[];new_state={}
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            for folder in FOLDERS:
                items,cursor=await self._folder(client,address,folder,state.get(folder),token);all_items.extend(items);new_state[folder]=cursor
                if len(all_items)>self.settings.max_sync_messages:raise RuntimeError("Graph sync exceeds configured message limit")
        return all_items,json.dumps(new_state)
class DelegatedGraphDeltaSync(GraphDeltaSync):
    def __init__(self,settings:Settings,refresh_token:str,authority_tenant:str|None=None):
        self.settings=settings;self.refresh_token=refresh_token;self.latest_refresh_token=refresh_token
        tenant=authority_tenant or settings.azure_tenant_id.strip() or "common"
        self.app=delegated_graph_application(settings,tenant)
    def _token_sync(self,force=False,send=False):
        scopes=delegated_auth_code_scopes(self.settings) if send else delegated_scopes(self.settings)
        result=_with_token_retry(lambda: self.app.acquire_token_by_refresh_token(self.refresh_token,scopes=scopes),"Delegated Graph token refresh failed")
        if "refresh_token" in result:self.latest_refresh_token=result["refresh_token"]
        if "access_token" not in result:raise RuntimeError(_token_error(result,"Delegated Graph token refresh failed"))
        return result["access_token"]
    async def _send_token(self):return await asyncio.to_thread(self._token_sync,False,True)
    def _send_mail_url(self,address:str)->str:
        del address
        return "https://graph.microsoft.com/v1.0/me/sendMail"
    def _message_url(self,address:str,message_id:str)->str:
        del address
        return f"https://graph.microsoft.com/v1.0/me/messages/{quote(message_id,safe='')}?$select=body"
    def _reply_url(self,address:str,message_id:str)->str:
        del address
        return f"https://graph.microsoft.com/v1.0/me/messages/{quote(message_id,safe='')}/reply"
    async def _folder(self,client,address,folder,url,token):
        fields="id,conversationId,internetMessageId,conversationIndex,subject,from,toRecipients,receivedDateTime,sentDateTime,parentFolderId,internetMessageHeaders,categories";url=url or f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages/delta?$select={fields}";items=[];attempts=0;delta=url
        while url:
            response=await _with_request_retry(lambda: client.get(validate_graph_url(url,self.settings),headers={"Authorization":f"Bearer {token}"}),"Graph request failed")
            if response.status_code==429 and attempts<4:await asyncio.sleep(_retry_delay(response.headers.get("Retry-After"),attempts));attempts+=1;continue
            if response.status_code>=400:raise RuntimeError(_graph_error(response))
            body=response.json()
            for item in body.get("value",[]):
                item["_folder"]=folder;items.append(item)
                if len(items)>self.settings.max_sync_messages:raise RuntimeError("Graph sync exceeds configured message limit")
            url=body.get("@odata.nextLink");delta=body.get("@odata.deltaLink",delta)
            if url:validate_graph_url(url,self.settings)
            if delta:validate_graph_url(delta,self.settings)
        return items,delta
