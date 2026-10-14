import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings,get_settings
from app.models.entities import Mailbox


class SecretCipher:
    def __init__(self,settings:Settings):
        self.current_id=settings.token_encryption_key_id
        current=settings.token_encryption_key
        if not current:
            if settings.production:raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
            current=base64.urlsafe_b64encode(hashlib.sha256((settings.jwt_secret+"\0oeis-development-token-key").encode()).digest()).decode()
        configured={self.current_id:current}
        try:configured.update(json.loads(settings.token_encryption_previous_keys))
        except (TypeError,ValueError) as exc:raise RuntimeError("TOKEN_ENCRYPTION_PREVIOUS_KEYS must be a JSON object") from exc
        self.keys={key_id:self._decode(value) for key_id,value in configured.items()}

    @staticmethod
    def _decode(value:str)->bytes:
        try:key=base64.urlsafe_b64decode(value.encode())
        except Exception as exc:raise RuntimeError("Token encryption key is not valid URL-safe base64") from exc
        if len(key)!=32:raise RuntimeError("Token encryption keys must decode to exactly 32 bytes")
        return key

    def encrypt(self,value:str,aad:str)->tuple[str,str,str]:
        nonce=os.urandom(12)
        ciphertext=AESGCM(self.keys[self.current_id]).encrypt(nonce,value.encode(),aad.encode())
        return base64.urlsafe_b64encode(ciphertext).decode(),base64.urlsafe_b64encode(nonce).decode(),self.current_id

    def decrypt(self,ciphertext:str,nonce:str,key_id:str,aad:str)->str:
        key=self.keys.get(key_id)
        if not key:raise RuntimeError(f"Token encryption key {key_id!r} is unavailable")
        raw=AESGCM(key).decrypt(base64.urlsafe_b64decode(nonce),base64.urlsafe_b64decode(ciphertext),aad.encode())
        return raw.decode()


def mailbox_aad(mailbox:Mailbox)->str:return f"oeis:mailbox:{mailbox.id}:{mailbox.provider}"


def set_mailbox_token(mailbox:Mailbox,value:str,settings:Settings|None=None)->None:
    ciphertext,nonce,key_id=SecretCipher(settings or get_settings()).encrypt(value,mailbox_aad(mailbox))
    mailbox.token_ciphertext=ciphertext;mailbox.token_nonce=nonce;mailbox.token_key_id=key_id;mailbox.graph_refresh_token=None


def get_mailbox_token(mailbox:Mailbox,settings:Settings|None=None)->str|None:
    if mailbox.token_ciphertext:
        if not mailbox.token_nonce or not mailbox.token_key_id:raise RuntimeError("Encrypted mailbox token metadata is incomplete")
        return SecretCipher(settings or get_settings()).decrypt(mailbox.token_ciphertext,mailbox.token_nonce,mailbox.token_key_id,mailbox_aad(mailbox))
    return mailbox.graph_refresh_token


def set_mailbox_azure_secret(mailbox:Mailbox,value:str,settings:Settings|None=None)->None:
    ciphertext,nonce,key_id=SecretCipher(settings or get_settings()).encrypt(value,f"oeis:mailbox:{mailbox.id}:azure-client-secret")
    mailbox.azure_secret_ciphertext=ciphertext;mailbox.azure_secret_nonce=nonce;mailbox.azure_secret_key_id=key_id


def mailbox_graph_settings(mailbox:Mailbox,settings:Settings|None=None)->Settings:
    settings=settings or get_settings()
    if not mailbox.azure_client_id:
        return settings
    secret=SecretCipher(settings).decrypt(mailbox.azure_secret_ciphertext,mailbox.azure_secret_nonce,mailbox.azure_secret_key_id,f"oeis:mailbox:{mailbox.id}:azure-client-secret") if mailbox.azure_secret_ciphertext else settings.azure_client_secret
    return settings.model_copy(update={"azure_client_id":mailbox.azure_client_id,"azure_tenant_id":mailbox.azure_tenant_id or "","azure_client_secret":secret,"azure_client_certificate_path":""})


def migrate_mailbox_token(mailbox:Mailbox,settings:Settings|None=None)->bool:
    configured=settings or get_settings();cipher=SecretCipher(configured)
    if mailbox.graph_refresh_token:set_mailbox_token(mailbox,mailbox.graph_refresh_token,configured);return True
    if mailbox.token_ciphertext and mailbox.token_key_id!=cipher.current_id:
        value=get_mailbox_token(mailbox,configured);set_mailbox_token(mailbox,value,configured);return True
    return False
