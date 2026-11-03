"""Model variants that can be seated in a room, beyond the agents listed in agents.yaml.

Every variant becomes one more agent *type* in the picker (own handle, name, face, shirt colour),
inheriting folders / network / approval settings from the configured agent of the same provider.
Codex models are read from the local Codex model cache so new releases appear automatically."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

# (handle, model for `claude --model`, colour, role)
ANTHROPIC_PALETTE = {"fable": "#b07fd6", "haiku": "#e0b050", "opus": "#c9644a", "sonnet": "#5a7fc0"}
ANTHROPIC_FACE_POOL = [8, 9, 11, 4]
ANTHROPIC_ROLES = {"fable": "Deep reasoner. Hard problems, long analyses and careful reviews.",
                   "haiku": "Very fast helper for small, simple tasks.",
                   "opus": "Strongest Opus model, pinned to this exact version.",
                   "sonnet": "Balanced fast helper, pinned to this exact version."}
# Offline fallback, used when no Anthropic API key is stored or the lookup fails.
ANTHROPIC = [
    ("fable-5p1", "claude-fable-5-1", "#b07fd6", "Deep reasoner. Hard problems, long analyses and careful reviews."),
    ("haiku-5p5", "claude-haiku-5-5", "#e0b050", "Very fast helper for small, simple tasks."),
    ("opus-5p5", "claude-opus-5-5", "#c9644a", "Pinned Opus 5.5 (same model as @claude, fixed version)."),
    ("sonnet-5p5", "claude-sonnet-5-5", "#5a7fc0", "Pinned Sonnet 5.5 (same model as @sonnet, fixed version)."),
]
# Fallback when the Codex cache is missing.
CODEX_FALLBACK = ["gpt-6.1-sol", "gpt-6-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-6-luna",
                  "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
OPENAI_FACES = [7, 10, 12, 13, 1, 2, 5, 7]
OPENAI_COLORS = ["#0e8a6c", "#3fb8a0", "#7bd3b5", "#4fa8d8", "#2c7fa0", "#8fc46a", "#5dbd8a", "#9ad0c2"]
OPENAI_ROLES = {"sol": "Largest GPT model. Independent deep cross-checks and alternative approaches.",
                "astra": "Large GPT model. Independent cross-checks and alternative approaches.",
                "terra": "Mid-size GPT model. Balanced second opinions and HTML pages.",
                "luna": "Small, fast GPT model. Quick scripts and cheap cross-checks."}


def _codex_models() -> list[str]:
    cache = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "models_cache.json"
    try:
        data = json.loads(cache.read_text())
        items = data.get("models", data) if isinstance(data, dict) else data
        slugs = [m["slug"] for m in items if m.get("visibility") == "list" and m.get("slug")]
        return slugs or CODEX_FALLBACK
    except Exception:
        return CODEX_FALLBACK


def _anthropic_models() -> list[tuple[str, str, str, str, int | None]]:
    """Live lookup of Claude models (needs the Anthropic key in the keychain); static list if unavailable."""
    try:
        from .keys import get_key
        key = get_key("anthropic")[0]
        if not key:
            raise LookupError
        req = urllib.request.Request("https://api.anthropic.com/v1/models?limit=100",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        ids = [m["id"] for m in json.load(urllib.request.urlopen(req, timeout=4))["data"]]
        out = []
        for mid in ids:
            fam = next((f for f in ANTHROPIC_PALETTE if f in mid), None)
            if not fam or not mid.startswith("claude-"):
                continue
            handle = re.sub(r"-\d{8}$", "", mid.removeprefix("claude-"))   # drop dated snapshot suffixes first
            handle = re.sub(r"(?<=\d)-(?=\d)", "p", handle)
            out.append((handle, mid, ANTHROPIC_PALETTE[fam], ANTHROPIC_ROLES[fam]))
        if out:
            return out
    except Exception:
        pass
    return ANTHROPIC


def _handle(slug: str) -> str:
    return slug.lower().replace(".", "").replace("_", "-")   # gpt-6.1-sol -> gpt-61-sol (no dots in @handles)


def extend_catalog(agents: list[dict]) -> list[dict]:
    """Configured agents first (unchanged), then one extra type per known model variant not already configured."""
    out = list(agents)
    have_models = {(a.get("provider"), str(a.get("model") or "").lower()) for a in agents}
    have_names = {a["name"].lower() for a in agents}
    tpl = {}
    for a in agents:
        tpl.setdefault(a.get("provider"), a)

    def add(name, provider, model, color, role, face=None):
        if name in have_names or (provider, model.lower()) in have_models or provider not in tpl:
            return
        keep = {k: v for k, v in tpl[provider].items()
                if k not in ("name", "model", "color", "role", "person", "face", "voice", "supervisor")}
        out.append({**keep, "name": name, "provider": provider, "model": model, "color": color, "role": role, "extra": True, **({"face": face} if face else {})})
        have_names.add(name)

    for i, (handle, model, color, role) in enumerate(_anthropic_models()):
        add(handle, "claude-code", model, color, role, ANTHROPIC_FACE_POOL[i % len(ANTHROPIC_FACE_POOL)])
    for i, slug in enumerate(_codex_models()):
        add(_handle(slug), "codex", slug, OPENAI_COLORS[i % len(OPENAI_COLORS)],
            OPENAI_ROLES.get(slug.rsplit("-", 1)[-1], "GPT model. Independent cross-checks."), OPENAI_FACES[i % len(OPENAI_FACES)])
    return out
