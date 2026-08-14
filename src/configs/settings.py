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

    # Worker count for parallel dataset processing (main.py). Defaults to
    # 4 — a conservative starting point (~1GB budget per worker per the
    # 9,610-file / ~150MB-output-per-dataset estimate). Override via
    # MANUAL_PARSER_MAX_WORKERS in .env once you've measured actual peak
    # RSS on one real run against your machine's available RAM.
    max_workers: int = 4

    # Skip datasets whose output already exists (main.json present) on
    # re-run, instead of reprocessing from scratch — see resumability.
    skip_existing: bool = True

settings = Settings()