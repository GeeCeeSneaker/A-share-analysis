"""Structural application configuration from configs/base.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


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
