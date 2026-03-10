"""
Load scraper-specific configuration from JSON files.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import os

from pink_tax.config import load_dotenv

load_dotenv()

def _env_key(source_name: str) -> str:
    """
    Build env var key for per-source config override.
    """

    return f"PINK_TAX_SCRAPER_CONFIG_{source_name.upper()}"

def load_scraping_source_config(root: Path, source_name: str) -> dict:
    """
    Load one scraping source config JSON, with optional env override path.
    """

    override = os.getenv(_env_key(source_name), "").strip()
    config_path = Path(override) if override else root / "config" / "scraping" / f"{source_name}.json"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing scraper config for '{source_name}': {config_path}. "
            "Add the file or set env override."
        )

    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)

def cfg_str(config: dict[str, Any], key: str, default: str) -> str:
    """
    Read a string value from config with fallback.
    """

    value = config.get(key, default)
    if value is None:
        return default
    return str(value)

def cfg_int(config: dict[str, Any], key: str, default: int) -> int:
    """
    Read an int value from config with fallback.
    """

    value = config.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def cfg_float(config: dict[str, Any], key: str, default: float) -> float:
    """
    Read a float value from config with fallback.
    """

    value = config.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def cfg_list(config: dict[str, Any], key: str, default: list[str]) -> list[str]:
    """
    Read a string list from config with fallback.
    """

    value = config.get(key)
    if isinstance(value, list):
        out = [str(item).strip() for item in value if str(item).strip()]
        return out or list(default)
    return list(default)

def cfg_path(root: Path, config: dict[str, Any], key: str, default: str) -> Path:
    """
    Read a filesystem path from config and resolve against repo root.
    """

    raw = cfg_str(config, key, default).strip()
    path = Path(raw)
    return path if path.is_absolute() else root / path

def cfg_delay(
    config: dict[str, Any],
    key_prefix: str,
    default_min: float,
    default_max: float,
) -> tuple[float, float]:
    """
    Read delay range from config using <prefix>_min_seconds and <prefix>_max_seconds.
    """

    min_value = cfg_float(config, f"{key_prefix}_min_seconds", default_min)
    max_value = cfg_float(config, f"{key_prefix}_max_seconds", default_max)

    if min_value <= 0 or max_value <= 0:
        return default_min, default_max
    if min_value > max_value:
        return max_value, min_value
    return min_value, max_value