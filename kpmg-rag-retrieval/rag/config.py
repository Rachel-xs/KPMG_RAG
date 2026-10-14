"""Load config.yaml and resolve paths relative to the repo root."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_config(path: str | Path | None = None) -> dict:
    _load_dotenv(ROOT / ".env")
    path = Path(path) if path else ROOT / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["user_agent"] = os.environ.get("SEC_USER_AGENT", cfg.get("user_agent", ""))
    cfg["paths"] = {k: (ROOT / v) for k, v in cfg["paths"].items()}
    return cfg
