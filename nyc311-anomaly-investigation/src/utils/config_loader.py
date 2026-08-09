"""Load YAML config and logging setup once, from anywhere in the repo."""
from __future__ import annotations

import functools
import logging.config
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@functools.lru_cache(maxsize=1)
def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    with open(path or CONFIG_DIR / "config.yaml") as fh:
        return yaml.safe_load(fh)


def setup_logging(path: str | Path | None = None) -> None:
    with open(path or CONFIG_DIR / "logging.yaml") as fh:
        logging.config.dictConfig(yaml.safe_load(fh))


def env(key: str, default: str | None = None) -> str:
    load_dotenv(ROOT / ".env")
    value = os.getenv(key, default)
    if value is None:
        raise KeyError(f"Missing required environment variable: {key}")
    return value
