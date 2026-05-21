"""Runtime configuration loaded from environment + optional .env file.

Precedence (highest first):
  1. Real process env vars (set by shell, Render, systemd, etc.)
  2. Values in a local ``.env`` file at the repo root (git-ignored)
  3. Hard-coded defaults below

Use ``settings = get_settings()`` from anywhere in the app. The result is
cached so the .env file is read once per process.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Load .env once, without overriding real env vars.
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    yclaude_base_url: str
    yclaude_api_key: str
    yclaude_client_id: str
    yclaude_model: str | None
    yclaude_timeout: float

    @property
    def yclaude_enabled(self) -> bool:
        return bool(self.yclaude_base_url and self.yclaude_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        yclaude_base_url=os.environ.get("YCLAUDE_BASE_URL", "").rstrip("/"),
        yclaude_api_key=os.environ.get("YCLAUDE_API_KEY", ""),
        yclaude_client_id=os.environ.get("YCLAUDE_CLIENT_ID", "ydocter"),
        yclaude_model=os.environ.get("YCLAUDE_MODEL") or None,
        yclaude_timeout=float(os.environ.get("YCLAUDE_TIMEOUT", "120")),
    )
