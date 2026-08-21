"""Application configuration.

Secrets come from environment / .env (never committed); structural settings
come from configs/base.yaml. M0 keeps this deliberately thin.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secret / environment settings loaded from .env or the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tgw_username: str = ""
    tgw_password: str = ""
    tgw_server_vip: str = ""
    tgw_server_port: int = 8000
    tgw_module: str = "AmazingData"


class DiskWatermark(BaseModel):
    warn_free_pct: int = 20
    clean_free_pct: int = 15
    block_free_pct: int = 10


class SpikeThrottle(BaseModel):
    request_interval_seconds: float = 1.0
    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0
    batch_size: int = 1000


class Paths(BaseModel):
    data_root: Path = Path("data")
    duckdb_path: Path = Path("data/db/atlas.duckdb")
    staging_root: Path = Path("data/staging")
    spike_root: Path = Path("data/spike")


class AppConfig(BaseModel):
    """Structural configuration (configs/base.yaml)."""

    paths: Paths = Field(default_factory=Paths)
    timezone_display: str = "Asia/Shanghai"
    eod_signal_time: str = "17:30"
    spike: SpikeThrottle = Field(default_factory=SpikeThrottle)
    disk_watermark: DiskWatermark = Field(default_factory=DiskWatermark)


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load structural config from YAML; missing file yields defaults."""
    if config_path is None:
        config_path = Path("configs/base.yaml")
    if not config_path.is_file():
        return AppConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    # flatten the yaml layout (data_root/duckdb_path/staging_root/spike_root at top level)
    paths = {
        k: raw[k] for k in ("data_root", "duckdb_path", "staging_root", "spike_root") if k in raw
    }
    tz = raw.get("timezone", {})
    data = {
        "paths": paths,
        "timezone_display": tz.get("display", "Asia/Shanghai"),
        "eod_signal_time": raw.get("eod_signal_time", "17:30"),
        "spike": raw.get("spike", {}),
        "disk_watermark": raw.get("disk_watermark", {}),
    }
    return AppConfig.model_validate(data)
