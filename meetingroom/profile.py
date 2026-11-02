"""The user's own display name: asked once on first launch, kept beside the meetings, editable in Settings."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_NAME = "Berkin"


def _file(cfg: dict) -> Path:
    return Path(cfg.get("workspace", "~/MeetingRoom")).expanduser() / "profile.json"


def clean(name) -> str:
    return " ".join(str(name or "").split())[:40]


def load(cfg: dict) -> str | None:
    """The saved name, or None until the user has chosen one."""
    try:
        return clean(json.loads(_file(cfg).read_text(encoding="utf-8")).get("name")) or None
    except (OSError, ValueError, AttributeError):
        return None


def save(cfg: dict, name: str) -> str:
    name = clean(name)
    if not name:
        raise ValueError("name is empty")
    f = _file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"name": name}), encoding="utf-8")
    return name
