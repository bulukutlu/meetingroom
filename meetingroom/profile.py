"""The user's own display name: asked once on first launch, kept beside the meetings, editable in Settings."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_NAME = "Berkin"


def _file(cfg: dict) -> Path:
    return Path(cfg.get("workspace", "workspace")).expanduser() / "profile.json"


def clean(name) -> str:
    return " ".join(str(name or "").split())[:40]


def _read(cfg: dict) -> dict:
    try:
        d = json.loads(_file(cfg).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(cfg: dict, **kv) -> None:
    f = _file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({**_read(cfg), **kv}), encoding="utf-8")


def load(cfg: dict) -> str | None:
    """The saved name, or None until the user has chosen one."""
    return clean(_read(cfg).get("name")) or None


def load_speech(cfg: dict) -> dict:
    """Speech models picked in Settings: {"stt_model": ..., "tts_model": ...} (missing = agents.yaml / default)."""
    d = _read(cfg)
    return {k: str(d[k]) for k in ("stt_model", "tts_model") if d.get(k)}


def save_speech(cfg: dict, **models) -> None:
    _write(cfg, **{k: v for k, v in models.items() if k in ("stt_model", "tts_model") and v})


def save(cfg: dict, name: str) -> str:
    name = clean(name)
    if not name:
        raise ValueError("name is empty")
    _write(cfg, name=name)
    return name
