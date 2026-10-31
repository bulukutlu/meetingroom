"""API key handling.

Keys live ONLY in your operating system's credential store
(macOS Keychain, Windows Credential Manager, or the Secret Service /
KWallet on Linux) via the `keyring` package. They are never written to a
file by this app, never sent to the browser, and never logged.

As a fallback (e.g. a headless Linux box without a keyring), an
environment variable set in your current shell is accepted.
"""
from __future__ import annotations

import os

SERVICE = "meetingroom"
PROVIDERS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    kr = keyring.get_keyring()
    # Refuse "no backend" and any plaintext-file backends.
    name = type(kr).__module__ + "." + type(kr).__name__
    if isinstance(kr, fail.Keyring) or "plaintext" in name.lower() or "file" in name.lower().split(".")[-1]:
        return None
    return keyring


def backend_name() -> str:
    kr = _keyring()
    if kr is None:
        return "none (no secure OS keyring found)"
    k = kr.get_keyring()
    return type(k).__module__ + "." + type(k).__name__


def get_key(provider: str) -> tuple[str | None, str]:
    """Return (key, source) where source is 'keyring', 'env' or 'missing'."""
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(SERVICE, provider)
            if v:
                return v, "keyring"
        except Exception:
            pass
    env = PROVIDERS.get(provider)
    if env and os.environ.get(env):
        return os.environ[env], "env"
    return None, "missing"


def set_key(provider: str, value: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError(
            "No secure OS keyring is available, so the key was NOT saved.\n"
            "On Linux install a Secret Service provider (e.g. gnome-keyring) or set "
            f"{PROVIDERS[provider]} in your shell for this session only."
        )
    kr.set_password(SERVICE, provider, value)


def delete_key(provider: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, provider)
        return True
    except Exception:
        return False


def mask(v: str | None) -> str:
    if not v:
        return "-"
    return v[:6] + "…" + v[-4:] if len(v) > 14 else "set"
