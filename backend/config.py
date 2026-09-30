"""Application configuration loaded exclusively from environment variables.

Secrets are read from the environment (optionally via a local ``.env`` file)
and are never written to logs, never returned by any HTTP route, and never
placed in the browser payload.
"""

import json
from functools import lru_cache
from typing import Annotated, List, Literal, Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "production", "test"]

# Origins allowed during local development. Production must configure
# CORS_ORIGINS explicitly; a wildcard is never assumed.
LOCAL_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class Settings(BaseSettings):
    """Runtime settings for the backend service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Service identity -------------------------------------------------
    app_name: str = Field(default="Live Fact-Checker Backend")
    app_version: str = Field(default="0.1.0")
    environment: Environment = Field(default="development")

    # --- HTTP server ------------------------------------------------------
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)

    # --- CORS -------------------------------------------------------------
    # `NoDecode` stops pydantic-settings from running json.loads() on the raw
    # environment value. Without it, any CORS_ORIGINS that is not valid JSON
    # (for example the comma-separated form this project documents) raises
    # SettingsError while the settings object is being built, which fails the
    # module import and takes the whole application down.
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: list(LOCAL_DEV_ORIGINS),
        description="Comma-separated list of allowed browser origins.",
    )

    # --- Logging ----------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_json: bool = Field(
        default=False,
        description="Emit machine-readable JSON logs instead of human-readable text.",
    )

    # --- Engine wiring ----------------------------------------------------
    use_mock_engines: bool = Field(
        default=True,
        description=(
            "True selects the deterministic offline mock engines. False selects "
            "the real modules: claim extraction runs through LLMClaimEngine "
            "against the OpenAI-compatible LLM Gateway, while verification runs "
            "through the existing `verification` package. This single switch is "
            "all that is needed to move between mock and real mode."
        ),
    )

    # --- Credentials (server-side only, never exposed to the browser) -----
    assemblyai_api_key: Optional[SecretStr] = Field(default=None)
    llm_gateway_api_key: Optional[SecretStr] = Field(default=None)
    llm_gateway_base_url: str = Field(
        default="https://api.assemblyai.com/llm/v1",
        description="Base URL for the LLM Gateway API (OpenAI-compatible).",
    )
    llm_gateway_model: str = Field(
        default="qwen3.5-4b-32k-fast",
        description="Model name to use for the LLM Gateway.",
    )
    search_api_key: Optional[SecretStr] = Field(default=None)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string, a JSON array, or a real list.

        Deployment platforms often store a variable as either
        ``https://a.example.com,https://b.example.com`` or
        ``["https://a.example.com","https://b.example.com"]``; both must work
        without raising.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return list(LOCAL_DEV_ORIGINS)
            if stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, list):
                    return [str(item).strip() for item in decoded if str(item).strip()]
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            return "INFO"
        return level

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def resolved_cors_origins(self) -> List[str]:
        """Return CORS origins, rejecting an unsafe wildcard in production."""
        origins = [origin for origin in self.cors_origins if origin]
        if not origins:
            return list(LOCAL_DEV_ORIGINS)
        if self.is_production and "*" in origins:
            raise ValueError(
                "CORS_ORIGINS='*' is not permitted when ENVIRONMENT=production. "
                "List the deployed frontend origin(s) explicitly."
            )
        return origins

    def has_assemblyai_key(self) -> bool:
        return bool(self.assemblyai_api_key and self.assemblyai_api_key.get_secret_value())

    def has_llm_gateway_key(self) -> bool:
        return bool(self.llm_gateway_api_key and self.llm_gateway_api_key.get_secret_value())

    def has_search_key(self) -> bool:
        return bool(self.search_api_key and self.search_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance.

    Cached so the environment is parsed once per process. Tests can clear the
    cache with ``get_settings.cache_clear()`` after changing the environment.
    """
    return Settings()
