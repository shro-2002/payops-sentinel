"""Environment configuration. Secrets stay server-side; nothing here is ever sent to the browser."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://payops:payops_local@localhost:5433/payops"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str = ""
    gemini_api_key: str = ""
    llm_provider: str = "gemini"  # gemini | anthropic
    llm_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    local_console: bool = False  # dev-only single-operator console (same LOCAL_CONSOLE flag the proxy reads)
    replay_llm: bool = False  # judge mode: replay a recorded Claude transcript (labelled REPLAY), no LLM key needed
    operator_token: str = ""  # bearer token required for every write endpoint
    operator_identity_public_key: str = ""  # base64 DER Ed25519 public key; proxy signs X-Operator with the private key
    max_tool_calls: int = 8
    refund_cap_minor: int = 2500  # policy cap per action: $25.00
    approval_ttl_minutes: int = 15
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
