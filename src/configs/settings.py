from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANUAL_PARSER_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore"
    )

    data_dir: Path = PROJECT_ROOT.parent / "data"
    output_dir: Path = PROJECT_ROOT.parent / "output"

settings = Settings()