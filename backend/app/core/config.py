from functools import lru_cache
import base64
import os
from pathlib import Path
from urllib.parse import urlparse
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ENV = Path(__file__).resolve().parents[2] / ".env"
BACKEND_DB = Path(__file__).resolve().parents[2] / "oeis.db"
ENV_FILES = () if os.environ.get("OEIS_DISABLE_ENV_FILE")=="true" else (".env", str(BACKEND_ENV))

class Settings(BaseSettings):
    environment: str = "development"
    app_name: str = "OEIS API"
    app_version: str = "1.0.0"
    database_url: str = f"sqlite:///{BACKEND_DB}"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "development-only-change-me-32-characters"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "oeis-api"
    jwt_audience: str = "oeis-web"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    max_sessions_per_user: int = 10
    login_max_failures: int = 5
    login_window_minutes: int = 15
    token_encryption_key: str = ""
    token_encryption_key_id: str = "v1"
    token_encryption_previous_keys: str = "{}"
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_client_certificate_path: str = ""
    azure_client_certificate_thumbprint: str = ""
    graph_scope: str = "https://graph.microsoft.com/.default"
    graph_allowed_hosts: str = "graph.microsoft.com"
    graph_redirect_uri: str = "http://localhost:8000/api/graph/oauth/callback"
    graph_delegated_scopes: str = "Mail.Read Mail.Send offline_access User.Read"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/gmail/oauth/callback"
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email"
    ai_api_key: str = ""
    ai_api_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o"
    ai_fallback_model: str = "gpt-4o-mini"
    frontend_url: str = "http://localhost:5173"
    sync_interval_seconds: int = 10
    scheduler_enabled: bool = True
    summary_hour: int
    app_timezone: str = "Asia/Kolkata"
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    bootstrap_admin_name: str
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    manager_email: str = ""
    director_email: str = ""
    dashboard_url: str = "http://localhost:8080"
    manager_tenant_wide_access: bool = False
    max_report_rows: int = 10000
    max_sync_messages: int = 10000
    max_request_bytes: int = 1048576
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    enable_api_docs: bool = True
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    @property
    def production(self)->bool:return self.environment.strip().lower()=="production"

    def validate_security(self)->None:
        if self.jwt_algorithm!="HS256":raise RuntimeError("JWT_ALGORITHM must be HS256")
        if not self.production:return
        weak={"development-only-change-me-32-characters","replace-with-at-least-32-random-characters","change-me","secret"}
        if self.jwt_secret in weak or len(self.jwt_secret.encode())<32:raise RuntimeError("Production JWT_SECRET must contain at least 32 random bytes")
        if not 1<=self.access_token_minutes<=15 or not 1<=self.refresh_token_days<=30 or self.max_sessions_per_user<1:raise RuntimeError("Production session lifetimes or limits are insecure")
        try:
            key=base64.urlsafe_b64decode(self.token_encryption_key.encode())
        except Exception as exc:raise RuntimeError("TOKEN_ENCRYPTION_KEY must be URL-safe base64") from exc
        if len(key)!=32:raise RuntimeError("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
        if len(self.bootstrap_admin_password)<6 or self.bootstrap_admin_password in {"replace-before-first-start","OEIS-Admin@July2026#47"}:raise RuntimeError("Production bootstrap Admin password must have at least 6 characters and not use a known default")
        if self.database_url.startswith("sqlite"):raise RuntimeError("Production DATABASE_URL must not use SQLite")
        database_lower=self.database_url.lower()
        if database_lower.startswith("mssql") and ("encrypt=yes" not in database_lower or "trustservercertificate=no" not in database_lower):raise RuntimeError("Production SQL Server connection must verify TLS certificates")
        redis=urlparse(self.redis_url)
        if redis.scheme not in {"redis","rediss"} or not redis.password:raise RuntimeError("Production REDIS_URL must include authentication; use rediss across trust boundaries")
        if not self.allowed_hosts.strip() or "*" in self.allowed_hosts:raise RuntimeError("Production ALLOWED_HOSTS must contain exact hostnames")
        for name,value in {"FRONTEND_URL":self.frontend_url,"DASHBOARD_URL":self.dashboard_url,"GRAPH_REDIRECT_URI":self.graph_redirect_uri,"GOOGLE_REDIRECT_URI":self.google_redirect_uri}.items():
            if urlparse(value).scheme!="https":raise RuntimeError(f"{name} must use HTTPS in production")
        if self.enable_api_docs:raise RuntimeError("ENABLE_API_DOCS must be false in production")
        if self.azure_client_id and not self.azure_tenant_id:raise RuntimeError("AZURE_TENANT_ID is required when Microsoft OAuth is enabled")
        if self.google_client_id and not self.google_client_secret:raise RuntimeError("GOOGLE_CLIENT_SECRET is required when Gmail OAuth is enabled")


@lru_cache
def get_settings() -> Settings:
    return Settings()
