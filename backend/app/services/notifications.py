import smtplib
import ssl
import asyncio
from email.message import EmailMessage
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Mailbox,MailboxStatus
from app.services.graph import DelegatedGraphDeltaSync,GraphDeltaSync,delegated_authority_tenant
from app.services.secrets import get_mailbox_token,set_mailbox_token

def report_mailbox_available()->bool:
    with SessionLocal() as db:
        return any(mailbox.provider=="microsoft" and mailbox.status==MailboxStatus.ACTIVE and (get_mailbox_token(mailbox,get_settings()) or get_settings().azure_client_secret or get_settings().azure_client_certificate_path) for mailbox in db.scalars(select(Mailbox)))

def send_html(to:str,subject:str,html:str)->bool:
    s=get_settings()
    if not to:return False
    if not (s.smtp_host and s.smtp_username and s.smtp_password):
        with SessionLocal() as db:
            for mailbox in db.scalars(select(Mailbox).where(Mailbox.provider=="microsoft",Mailbox.status==MailboxStatus.ACTIVE).order_by(Mailbox.id)):
                refresh_token=get_mailbox_token(mailbox,s)
                if not refresh_token and not (s.azure_client_secret or s.azure_client_certificate_path):continue
                strategy=DelegatedGraphDeltaSync(s,refresh_token,delegated_authority_tenant(mailbox.address,s)) if refresh_token else GraphDeltaSync(s)
                asyncio.run(strategy.send_html(mailbox.address,to,subject,html))
                if refresh_token and strategy.latest_refresh_token!=refresh_token:
                    set_mailbox_token(mailbox,strategy.latest_refresh_token,s);db.commit()
                return True
        return False
    message=EmailMessage();message["From"]=s.smtp_from or s.smtp_username;message["To"]=to;message["Subject"]=subject;message.set_content("This notification requires an HTML-capable email client.");message.add_alternative(html,subtype="html")
    with smtplib.SMTP(s.smtp_host,s.smtp_port,timeout=30) as client:
        client.starttls(context=ssl.create_default_context());client.login(s.smtp_username,s.smtp_password);client.send_message(message)
    return True
