import asyncio

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.services import ai_provider
from app.services.ai_provider import MODELS, active_ai_settings, provider_status, save_ai_settings


def test_provider_selection_persists_and_keys_remain_hidden():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings = Settings.model_construct(ai_api_key="legacy-key", ai_api_base_url="https://openrouter.ai/api/v1",
                                        ai_model="legacy-model", ai_fallback_model="", jwt_secret="test-secret",
                                        token_encryption_key="", token_encryption_key_id="v1", token_encryption_previous_keys="{}",
                                        environment="development")
    with Session(engine) as db:
        save_ai_settings(db, "nvidia", next(iter(MODELS["nvidia"])), "nvidia-secret", settings)
        assert active_ai_settings(db, settings).ai_api_key == "nvidia-secret"
        assert "nvidia-secret" not in str(provider_status(db, settings))
        save_ai_settings(db, "openrouter", next(iter(MODELS["openrouter"])), None, settings)
        assert active_ai_settings(db, settings).ai_api_key == "legacy-key"
        save_ai_settings(db, "nvidia", next(iter(MODELS["nvidia"])), None, settings)
        assert active_ai_settings(db, settings).ai_api_key == "nvidia-secret"
    engine.dispose()


def test_connection_uses_saved_model_and_hides_provider_error(monkeypatch):
    requests = []
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def post(self, url, json, headers):
            requests.append((url, json, headers))
            return httpx.Response(404, json={"error": "sensitive provider response"})
    monkeypatch.setattr(ai_provider.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    settings = Settings.model_construct(ai_api_key="test-private-key", ai_api_base_url="https://provider.example/v1", ai_model="selected-model")
    result = asyncio.run(ai_provider.test_ai_connection(settings))
    assert result == {"ok": False, "status_code": 404, "message": "AI provider returned HTTP 404. The saved model may be unavailable for this key; choose another model."}
    assert requests[0][1]["model"] == "selected-model"
    assert requests[0][1]["messages"][0]["content"] == "Reply with OK."
    assert "test-private-key" not in str(result)
