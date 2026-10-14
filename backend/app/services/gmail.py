import asyncio
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

import httpx

from app.core.config import Settings
from app.services.graph import IMailSyncStrategy
from app.services.graph import _retry_delay


API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDERS = (("inbox", "INBOX", None), ("sentitems", "SENT", None), ("deleteditems", "TRASH", None), ("archive", None, "-in:inbox -in:sent -in:trash -in:spam"))
METADATA_HEADERS = ("From", "To", "Subject", "Date", "Message-ID", "In-Reply-To", "References")
ALLOWED_SCOPES = {"https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/userinfo.email", "openid"}


class _HTMLText(HTMLParser):
    def __init__(self): super().__init__();self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {"br","div","li","p","tr"}:self.parts.append("\n")
    def handle_data(self,data):self.parts.append(data)
    def text(self):return "".join(self.parts).strip()


def _decode_body(data: str) -> str:
    try:return base64.urlsafe_b64decode(data+"="*(-len(data)%4)).decode("utf-8",errors="replace")
    except (ValueError,TypeError):return ""


class GmailAPIError(RuntimeError):
    def __init__(self, response: httpx.Response):
        self.status_code = response.status_code
        self.reason = ""
        try:
            payload = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            self.reason = str(error.get("message") or error.get("status") or "").strip()
        except (ValueError, TypeError):
            self.reason = response.text[:240].strip()
        detail = f": {self.reason}" if self.reason else ""
        super().__init__(f"Gmail request failed ({response.status_code}){detail}")


def gmail_scopes(settings: Settings) -> list[str]:
    scopes=settings.gmail_scopes.split()
    required={"https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/userinfo.email"}
    if not set(scopes)<=ALLOWED_SCOPES or not required<=set(scopes):raise RuntimeError("Gmail scopes exceed OEIS allowlist")
    if "https://www.googleapis.com/auth/gmail.send" not in scopes:scopes.append("https://www.googleapis.com/auth/gmail.send")
    return scopes


class GmailDeltaSync(IMailSyncStrategy):
    def __init__(self, settings: Settings, refresh_token: str):
        self.settings = settings
        self.refresh_token = refresh_token
        self.access_token = ""

    async def _token(self) -> str:
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            response = await client.post(TOKEN_URL, data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            })
        if response.status_code >= 400:
            raise GmailAPIError(response)
        self.access_token = response.json()["access_token"]
        return self.access_token

    async def _get(self, client: httpx.AsyncClient, url: str, params: list[tuple[str, str]] | dict | None = None) -> dict:
        attempts = 0
        while True:
            if not self.access_token:
                await self._token()
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {self.access_token}"})
            if response.status_code == 401 and attempts == 0:
                self.access_token = ""
                attempts += 1
                continue
            if response.status_code == 429 and attempts < 4:
                await asyncio.sleep(_retry_delay(response.headers.get("Retry-After"),attempts))
                attempts += 1
                continue
            if response.status_code >= 400:
                raise GmailAPIError(response)
            return response.json()

    async def _message(self, client: httpx.AsyncClient, message_id: str) -> dict | None:
        params = [("format", "metadata"), *(("metadataHeaders", name) for name in METADATA_HEADERS)]
        try:
            body = await self._get(client, f"{API}/messages/{message_id}", params)
        except GmailAPIError as exc:
            if exc.status_code == 404:
                return {"id": message_id, "@removed": {"reason": "deleted"}}
            raise
        labels = set(body.get("labelIds", []))
        if "SPAM" in labels:
            return None
        folder = "inbox" if "INBOX" in labels else "sentitems" if "SENT" in labels else "deleteditems" if "TRASH" in labels else "archive"
        headers = {row.get("name", "").lower(): row.get("value", "") for row in body.get("payload", {}).get("headers", [])}
        sender = next((address for _, address in getaddresses([headers.get("from", "")]) if address), "unknown")
        recipients = [address for _, address in getaddresses([headers.get("to", "")]) if address]
        received = datetime.fromtimestamp(int(body.get("internalDate", "0")) / 1000, timezone.utc)
        try:
            sent = parsedate_to_datetime(headers["date"])
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            sent = sent.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            sent = received
        return {
            "id": body["id"],
            "conversationId": body.get("threadId"),
            "internetMessageId": headers.get("message-id"),
            "conversationIndex": body.get("threadId"),
            "subject": headers.get("subject") or "(no subject)",
            "from": {"emailAddress": {"address": sender}},
            "toRecipients": [{"emailAddress": {"address": address}} for address in recipients],
            "receivedDateTime": received.isoformat(),
            "sentDateTime": sent.isoformat(),
            "internetMessageHeaders": [{"name": name, "value": value} for name, value in headers.items()],
            "categories": sorted(labels),
            "_folder": folder,
        }

    async def message_content(self,address:str,message_id:str)->str:
        del address
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            body=await self._get(client,f"{API}/messages/{message_id}",{"format":"full"})
            plain=[];html=[];stack=[body.get("payload",{})]
            while stack:
                part=stack.pop();stack.extend(reversed(part.get("parts",[])))
                mime=part.get("mimeType","").lower()
                if mime not in {"text/plain","text/html"} or part.get("filename"):continue
                part_body=part.get("body",{});data=part_body.get("data")
                if not data and part_body.get("attachmentId"):
                    attachment=await self._get(client,f"{API}/messages/{message_id}/attachments/{part_body['attachmentId']}")
                    data=attachment.get("data")
                text=_decode_body(data or "")
                if text:(plain if mime=="text/plain" else html).append(text)
            content="\n\n".join(plain)
            if not content and html:
                parser=_HTMLText();parser.feed("\n\n".join(html));content=parser.text()
            return content[:1_000_000]

    async def send_reply(self,address:str,message_id:str,recipient:str,subject:str,body:str,internet_message_id:str|None=None,references:str|None=None,conversation_id:str|None=None)->None:
        del message_id
        message=EmailMessage();message["From"]=address;message["To"]=recipient;message["Subject"]=subject
        if internet_message_id:message["In-Reply-To"]=internet_message_id
        reference_values=[*(references or "").split(),*( [internet_message_id] if internet_message_id else [])]
        if reference_values:message["References"]=" ".join(dict.fromkeys(reference_values))
        message.set_content(body)
        payload={"raw":base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")}
        if conversation_id:payload["threadId"]=conversation_id
        if not self.access_token:await self._token()
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            response=await client.post(f"{API}/messages/send",json=payload,headers={"Authorization":f"Bearer {self.access_token}"})
        if response.status_code>=400:raise GmailAPIError(response)

    async def _list(self, client: httpx.AsyncClient, label: str | None, query: str | None) -> list[str]:
        ids = []
        page_token = None
        while True:
            params = {"maxResults": "500"}
            if label:
                params["labelIds"] = label
            if query:
                params["q"] = query
            if page_token:
                params["pageToken"] = page_token
            body = await self._get(client, f"{API}/messages", params)
            ids.extend(row["id"] for row in body.get("messages", []))
            if len(ids)>self.settings.max_sync_messages:raise RuntimeError("Gmail sync exceeds configured message limit")
            page_token = body.get("nextPageToken")
            if not page_token:
                return ids

    async def _initial(self, client: httpx.AsyncClient) -> list[dict]:
        seen = set()
        for _, label, query in FOLDERS:
            for message_id in await self._list(client, label, query):
                seen.add(message_id)
                if len(seen)>self.settings.max_sync_messages:raise RuntimeError("Gmail sync exceeds configured message limit")
        return await self._messages(client, seen)

    async def _messages(self, client: httpx.AsyncClient, message_ids) -> list[dict]:
        semaphore = asyncio.Semaphore(12)
        async def fetch(message_id):
            async with semaphore:
                return await self._message(client, message_id)
        items = await asyncio.gather(*(fetch(message_id) for message_id in message_ids))
        return [item for item in items if item]

    async def _history(self, client: httpx.AsyncClient, start_history_id: str) -> list[dict]:
        ids = set()
        page_token = None
        while True:
            params = {"startHistoryId": start_history_id, "maxResults": "500"}
            if page_token:
                params["pageToken"] = page_token
            body = await self._get(client, f"{API}/history", params)
            for history in body.get("history", []):
                for field in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                    ids.update(row["message"]["id"] for row in history.get(field, []))
                ids.update(row["message"]["id"] for row in history.get("messagesDeleted", []))
                if len(ids)>self.settings.max_sync_messages:raise RuntimeError("Gmail sync exceeds configured message limit")
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return await self._messages(client, ids)

    async def sync_mailbox(self, address: str, delta_state: str | None = None) -> tuple[list[dict], str]:
        del address
        await self._token()
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            if delta_state:
                try:
                    items = await self._history(client, delta_state)
                except GmailAPIError as exc:
                    if exc.status_code != 404:
                        raise
                    items = await self._initial(client)
            else:
                items = await self._initial(client)
            profile = await self._get(client, f"{API}/profile")
        return items, str(profile["historyId"])

    async def profile(self) -> dict:
        await self._token()
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            return await self._get(client, f"{API}/profile")
