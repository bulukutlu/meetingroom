"""Command line entry point.

    python -m meetingroom set-key anthropic     # stores key in OS keychain
    python -m meetingroom set-key openai
    python -m meetingroom keys                  # shows which keys are present (masked)
    python -m meetingroom remove-key openai
    python -m meetingroom run                   # start the meeting room
    python -m meetingroom run --demo            # try it with key-free demo agents
    python -m meetingroom run --agents claude,codex   # skip the picker, start only these
    python -m meetingroom run --all             # skip the picker, start everyone
    python -m meetingroom run --project ~/analysis          # meeting works in this folder
    python -m meetingroom run --ssh mybox --project ~/work  # agents run on a remote machine over SSH
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

import yaml

from . import keys

DEMO_CFG = {
    "user_name": "You",
    "workspace": "~/MeetingRoom-demo",
    "python": sys.executable,
    "agents": [
        {"name": "claude", "provider": "mock", "model": "demo", "color": "#d97757", "role": "Analysis lead"},
        {"name": "gpt", "provider": "mock", "model": "demo", "color": "#10a37f", "role": "Plotting and pages"},
        {"name": "sonnet", "provider": "mock", "model": "demo", "color": "#6a8fd8", "role": "Quick checks"},
    ],
}


def load_cfg(path: str | None) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "agents.yaml"
    if not p.exists():
        sys.exit(f"config not found: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    for bad in ("api_key", "key", "token", "secret"):
        if any(bad in (a or {}) for a in cfg.get("agents", [])) or bad in cfg:
            sys.exit(f"Refusing to start: '{bad}' found in {p}. Keys belong in the OS keychain "
                     "(python -m meetingroom set-key <provider>), never in config files.")
    cfg.setdefault("workspace", "~/MeetingRoom")
    cfg["python"] = os.path.expanduser(cfg.get("python") or sys.executable)
    return cfg


def main():
    ap = argparse.ArgumentParser(prog="meetingroom")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config")
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--demo", action="store_true", help="key-free demo agents")
    r.add_argument("--no-browser", action="store_true")
    r.add_argument("--agents", help="comma-separated agent names to start (skips the picker page)")
    r.add_argument("--all", action="store_true", help="start every configured agent (skips the picker page)")
    r.add_argument("--project", help="project folder the meeting works in (remote path with --ssh)")
    r.add_argument("--ssh", metavar="HOST", help="run the Claude Code / Codex agents on this SSH host")
    s = sub.add_parser("set-key"); s.add_argument("provider", choices=list(keys.PROVIDERS))
    d = sub.add_parser("remove-key"); d.add_argument("provider", choices=list(keys.PROVIDERS))
    sub.add_parser("keys")
    mn = sub.add_parser("minutes", help="(re)build minutes.md for a session folder")
    mn.add_argument("session_dir")
    a = ap.parse_args()

    if a.cmd == "minutes":
        from .minutes import build
        print(build(Path(a.session_dir).expanduser()))
        return
    if a.cmd == "set-key":
        v = getpass.getpass(f"Paste your {a.provider} API key (input hidden): ").strip()
        if not v:
            sys.exit("nothing entered")
        keys.set_key(a.provider, v)
        print(f"Saved to OS keychain ({keys.backend_name()}).")
        return
    if a.cmd == "remove-key":
        print("removed" if keys.delete_key(a.provider) else "nothing removed")
        return
    if a.cmd == "keys":
        print(f"keyring backend: {keys.backend_name()}")
        for p in keys.PROVIDERS:
            v, src = keys.get_key(p)
            print(f"  {p:10s} {src:8s} {keys.mask(v)}")
        return

    cfg = DEMO_CFG if a.demo else load_cfg(a.config)
    import uvicorn
    from .location import Location
    from .server import create_app

    token = secrets.token_urlsafe(24)  # new every start; never stored
    url = f"http://127.0.0.1:{a.port}/?t={token}"
    opener = None if a.no_browser else (lambda: threading.Timer(1.0, lambda: webbrowser.open(url)).start())
    all_agents = cfg["agents"]
    loc = Location.from_dict({"path": a.project or "", "host": a.ssh or ""})
    if a.ssh and not a.project:
        loc.path = "~"
    if err := loc.validate():
        sys.exit(err)
    if a.agents:
        want = [n.strip().lower() for n in a.agents.split(",") if n.strip()]
        known = {x["name"].lower() for x in all_agents}
        if bad := [n for n in want if n not in known]:
            sys.exit(f"unknown agent(s): {', '.join(bad)} (configured: {', '.join(sorted(known))})")
        names = [x["name"] for x in all_agents if x["name"].lower() in want]
    elif a.all or len(all_agents) < 2:
        names = [x["name"] for x in all_agents]
    else:
        from .picker import pick_agents
        print(f"\n  Choose participants in the browser: {url}\n")
        names, picked = pick_agents(all_agents, a.port, token, opener)
        if not (a.project or a.ssh):
            loc = picked
        opener = None   # already open; the page redirects itself into the room
    cfg = {**cfg, "agents": [x for x in all_agents if x["name"] in names], "location": loc}
    if loc.remote:
        print(f"  Connecting to {loc.host} ...")
        try:
            loc.connect(a.port, token)
        except Exception as e:
            sys.exit(str(e))
    app = create_app(cfg, a.port, token)
    print("\n  Meeting room running (only reachable from this computer)")
    print(f"  Participants: {', '.join('@' + x['name'] for x in cfg['agents'])}")
    if loc.label():
        print(f"  Project: {loc.label()}" + ("  (Claude Code / Codex agents run there over SSH)" if loc.remote else ""))
    print(f"  Open: {url}\n")
    if opener:
        opener()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
