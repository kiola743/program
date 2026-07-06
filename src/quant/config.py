"""YAML 설정 + .env 로더."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """config.yaml 과 .env 를 읽어 설정 dict 를 반환한다.

    .env 는 프로젝트 루트(현재 작업 디렉터리) 기준으로 찾는다.
    """
    load_dotenv()
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)
    return cfg


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default
