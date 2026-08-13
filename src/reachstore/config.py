from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    raw_dir: Path = Path("./data/raw")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
