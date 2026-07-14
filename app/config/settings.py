from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Spring Boot <-> FastAPI 내부 인증
    internal_api_key: str = Field(validation_alias="AI_INTERNAL_API_KEY")

    # OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Redis
    redis_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()