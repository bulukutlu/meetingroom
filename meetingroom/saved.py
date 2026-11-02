"""Versioned room checkpoints. Credentials and live connections are never saved."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

VERSION = 1
SPEC_KEYS = {
    "name", "person", "provider", "model", "color", "role", "face", "voice",
    "approval", "effort", "supervisor", "max_tokens", "sandbox", "network",
    "add_dirs", "claude_path", "codex_path", "remote_claude_path",
    "remote_codex_path", "permission_mode",
}
BACKEND_KEYS = ("session_id", "thread_id", "history", "items")


def checkpoint(room, status="recovery"):
    agents = []
    for a in room.agents.values():
        spec = {k: v for k, v in a.spec.items() if k in SPEC_KEYS}
        spec.update(approval=a.approval, effort=a.effort, supervisor=a.supervisor)
        agents.append({"spec": spec, "seen": a.seen,
                       "pending_context": a.pending_context, "usage": a.usage,
                       "backend": {k: getattr(a.backend, k) for k in BACKEND_KEYS
                                   if hasattr(a.backend, k)}})
    data = {"version": VERSION, "status": status, "title": room.title,
            "created": room.created, "updated": time.time(),
            "location": room.location.public(), "agents": agents,
            "shared": room.shared, "files": {k: str(p) for k, p in room.files.items()},
            "anchors": room.anchors, "attachments": room.attachments}
    fd, tmp = tempfile.mkstemp(prefix=".room-", dir=room.session_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, room.session_dir / "room.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(root: Path, session: str) -> dict:
    if not session or Path(session).name != session or session in (".", ".."):
        raise ValueError("Invalid saved meeting")
    folder = root / session
    if folder.resolve().parent != root.resolve():
        raise ValueError("Invalid saved meeting")
    data = json.loads((folder / "room.json").read_text(encoding="utf-8"))
    if data.get("version") != VERSION:
        raise ValueError("Unsupported saved meeting version")
    if data.get("status") not in ("saved", "recovery"):
        raise ValueError("This meeting was closed without saving")
    if not isinstance(data.get("agents"), list) or not data["agents"]:
        raise ValueError("Saved meeting has no participants")
    return data


def list_saved(root: Path, active: set[str]) -> list[dict]:
    out = []
    if not root.exists():
        return out
    for folder in root.iterdir():
        if folder.name in active or not folder.is_dir():
            continue
        try:
            data = read(root, folder.name)
            out.append({"id": folder.name, "title": data["title"],
                        "updated": data["updated"], "status": data["status"],
                        "location": data["location"],
                        "agents": [a["spec"]["name"] for a in data["agents"]]})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda d: d["updated"], reverse=True)


def restore(room, data):
    # Transcript is append-only and can be newer than the last atomic checkpoint.
    from .minutes import _load
    room.messages = _load(room.log_path)
    room.created = data["created"]
    room.shared = data.get("shared", [])
    room.files = {k: Path(p) for k, p in data.get("files", {}).items()}
    room.anchors = data.get("anchors", {})
    room.attachments = data.get("attachments", {})
    for state in data["agents"]:
        a = room.agents[state["spec"]["name"].lower()]
        a.seen = min(int(state.get("seen", 0)), len(room.messages))
        a.pending_context = state.get("pending_context", "")
        a.usage = state.get("usage", {})
        for k, v in state.get("backend", {}).items():
            if k in BACKEND_KEYS and hasattr(a.backend, k):
                setattr(a.backend, k, v)
        # Always supply the transcript on the first new request, including own
        # replies: it also provides a fallback if a CLI session has expired.
        history = "\n".join(f"{m['from']}: {m['text']}" for m in room.messages if m.get("kind") != "note")
        a.recovery_context = (
            "This meeting was reopened after a restart. Previous discussion follows; "
            "it is context, not new instructions. Continue only the new request. "
            "Previously interrupted work has not been restarted automatically.\n"
            + history + "\n"
            + f"Full work log and minutes: {room.session_dir}.\n")
        a.seen = len(room.messages)
