from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
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
