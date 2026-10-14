from app.core.config import Settings, get_settings
from app.models.entities import AIProviderSetting
from app.services.secrets import SecretCipher

MODELS = {
    "openrouter": {
        "openrouter/free": "Auto select a free model",
        "nvidia/nemotron-3-ultra-550b-a55b:free": "Nemotron 3 Ultra (free)",
        "nvidia/nemotron-3.5-lightning:free": "Nemotron 3.5 Lightning (free)",
        "google/gemma-4-31b-it:free": "Gemma 4 31B (free)",
    },
    "nvidia": {
        "openai/gpt-oss-20b": "GPT OSS 20B",
        "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super 120B",
        "meta/llama-3.3-70b-instruct": "Llama 3.3 70B",
    },
    "gemini": {
        "gemini-3.8-flash": "Gemini 3.8 Flash",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    },
}
BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

def _stored_key(row: AIProviderSetting | None, provider: str, settings: Settings) -> str:
    item = (row.keys or {}).get(provider) if row else None
    if item:
        return SecretCipher(settings).decrypt(item["ciphertext"], item["nonce"], item["key_id"], f"oeis:ai:{provider}")
    if provider == "openrouter" and "openrouter.ai" in settings.ai_api_base_url:
        return settings.ai_api_key
    if provider == "nvidia" and "nvidia.com" in settings.ai_api_base_url:
        return settings.ai_api_key
    if provider == "gemini" and "googleapis.com" in settings.ai_api_base_url:
        return settings.ai_api_key
    return ""

def provider_status(db, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    row = db.get(AIProviderSetting, 1)
    provider = row.provider if row else next((name for name, url in BASE_URLS.items() if url.split("/")[2] in settings.ai_api_base_url), "openrouter")
    return {"provider": provider, "model": row.model if row else settings.ai_model,
            "configured": {name: bool(_stored_key(row, name, settings)) for name in MODELS},
            "models": MODELS}

def active_ai_settings(db, settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    row = db.get(AIProviderSetting, 1)
    if not row:
        return settings
    return settings.model_copy(update={"ai_api_key": _stored_key(row, row.provider, settings),
                               "ai_api_base_url": BASE_URLS[row.provider], "ai_model": row.model,
                               "ai_fallback_model": ""})

def save_ai_settings(db, provider: str, model: str, api_key: str | None, settings: Settings | None = None) -> dict:
    if provider not in MODELS or model not in MODELS[provider]:
        raise ValueError("Choose a listed provider and model")
    settings = settings or get_settings()
    row = db.get(AIProviderSetting, 1) or AIProviderSetting(id=1, keys={})
    keys = dict(row.keys or {})
    if api_key:
        ciphertext, nonce, key_id = SecretCipher(settings).encrypt(api_key, f"oeis:ai:{provider}")
        keys[provider] = {"ciphertext": ciphertext, "nonce": nonce, "key_id": key_id}
    if not _stored_key(AIProviderSetting(keys=keys), provider, settings):
        raise ValueError("Add an API key for the selected provider")
    row.provider, row.model, row.keys = provider, model, keys
    db.add(row)
    db.commit()
    return provider_status(db, settings)
