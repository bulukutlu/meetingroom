"""Where a meeting takes place: a project folder on this computer, or a folder on
a remote machine reached over SSH (like Claude Code's remote sessions).

Local: every agent works inside the chosen folder.

SSH: Claude Code / Codex agents run *on the remote machine* (`ssh host claude -p
...`), so their tools act there. One SSH master connection per room carries a
reverse tunnel back to this computer's hub, which keeps approval cards and the
shared screen working; the MCP bridge is copied to ~/.meetingroom/ on the
remote and uploads shared files instead of passing paths. SSH must work without
a password prompt (keys or an agent), and claude / codex must be installed and
logged in on the remote.
"""
from __future__ import annotations

import os
import random
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BRIDGE = Path(__file__).with_name("mcp_bridge.py")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30"]
# ssh sockets: macOS $TMPDIR is long enough that $TMPDIR/name-%C plus ssh's temp suffix
# overflows the 104-byte sun_path limit, so prefer the short /tmp.
_SOCK_DIR = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
_PICKER_CP = os.path.join(_SOCK_DIR, "mr-pick-%C")


def rpath(p: str) -> str:
    """Quote a remote path for sh, keeping a leading ~ expandable."""
    p = (p or "~").strip()
    if p == "~":
        return '"$HOME"'
    if p.startswith("~/"):
        return '"$HOME"/' + shlex.quote(p[2:])
    return shlex.quote(p)


def login_sh(script: str) -> str:
    """Run `script` in the remote user's login shell so PATH matches an interactive session."""
    return 'exec "${SHELL:-/bin/sh}" -lc ' + shlex.quote(script)


def ssh_hosts() -> list[str]:
    """Concrete Host aliases from ~/.ssh/config (wildcards skipped)."""
    out: list[str] = []
    try:
        for line in (Path.home() / ".ssh" / "config").read_text(errors="replace").splitlines():
            m = re.match(r"\s*Host\s+(.+)", line, re.I)
            if m:
                out += [h for h in m.group(1).split() if not any(c in h for c in "*?!")]
    except OSError:
        pass
    return list(dict.fromkeys(out))


def _ssh(host: str, script: str, timeout: float = 25, cp: str = _PICKER_CP, stdin: str | None = None):
    cmd = ["ssh", *SSH_OPTS, "-o", "ControlMaster=auto", "-o", f"ControlPath={cp}", "-o", "ControlPersist=120",
           host, login_sh(script)]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
                          stdin=None if stdin is not None else subprocess.DEVNULL)


def _kv(text: str) -> dict:
    return dict(l.split("=", 1) for l in text.splitlines() if re.match(r"^[A-Z_a-z0-9]+=", l))


def list_dirs(path: str, host: str | None = None) -> dict:
    """Sub-folders of `path` (locally or on `host`) for the picker's folder browser."""
    if not host:
        p = Path(os.path.expanduser(path or "~")).resolve()
        if not p.is_dir():
            return {"error": f"{p} is not a folder"}
        try:
            dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))
        except OSError as e:
            return {"error": str(e)}
        return {"path": str(p), "parent": str(p.parent), "dirs": dirs[:400]}
    try:
        r = _ssh(host, f"cd -- {rpath(path)} && echo \"DIR=$(pwd)\" && "
                       "for d in */; do [ -d \"$d\" ] && echo \"D=${d%/}\"; done 2>/dev/null | head -400")
    except subprocess.TimeoutExpired:
        return {"error": f"ssh {host}: timed out"}
    kv = [l.split("=", 1) for l in r.stdout.splitlines() if l.startswith(("DIR=", "D="))]
    cur = next((v for k, v in kv if k == "DIR"), None)
    if r.returncode or not cur:
        return {"error": (r.stderr.strip().splitlines() or [f"cannot open {path}"])[-1]}
    return {"path": cur, "parent": str(Path(cur).parent), "dirs": sorted(v for k, v in kv if k == "D" and v != "*")}


def probe(host: str, path: str) -> dict:
    """Check an SSH target: reachable, folder exists, which agent CLIs are installed."""
    script = (f"cd -- {rpath(path)} 2>/dev/null && echo \"DIR=$(pwd)\"; echo \"HOME=$HOME\"; "
              "for t in claude codex python3; do p=$(command -v $t 2>/dev/null); "
              # login shells skip ~/.bashrc, so npm/nvm installs (typical for codex) are missed: look in the usual places
              "[ -z \"$p\" ] && for d in ~/.local/bin ~/.npm-global/bin ~/.volta/bin ~/.bun/bin ~/.nvm/versions/node/*/bin /usr/local/bin /opt/homebrew/bin; do "
              "[ -x \"$d/$t\" ] && p=$d/$t && break; done; echo \"BIN_$t=$p\"; done")
    try:
        r = _ssh(host, script)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ssh {host}: timed out"}
    kv = _kv(r.stdout)
    if "HOME" not in kv:
        err = (r.stderr.strip().splitlines() or ["no response"])[-1]
        return {"ok": False, "error": f"ssh {host} failed: {err} (password logins are not supported; use a key or ssh-agent)"}
    if not kv.get("DIR"):
        return {"ok": False, "error": f"folder {path} does not exist on {host}"}
    bins = {t: kv.get(f"BIN_{t}", "") for t in ("claude", "codex", "python3")}
    if not bins["python3"]:
        return {"ok": False, "error": f"python3 not found on {host} (needed for the meeting bridge)"}
    return {"ok": True, "host": host, "path": kv["DIR"], "home": kv["HOME"], "bins": bins}


@dataclass
class Location:
    kind: str = "default"       # default (each agent's own folder) | local | ssh
    path: str = ""
    host: str = ""
    home: str = ""              # remote $HOME (ssh)
    bins: dict = field(default_factory=dict)   # remote executables (ssh)
    rport: int = 0              # remote end of the reverse tunnel to the hub
    cp: str = ""                # ssh ControlPath of the room's master connection
    url_base: str = ""          # the room's path on the hub (/r/<id>)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Location":
        d = d or {}
        kind = d.get("kind") or ("ssh" if d.get("host") else "local" if d.get("path") else "default")
        loc = cls(kind=kind, path=str(d.get("path") or "").strip(), host=str(d.get("host") or "").strip())
        if loc.kind == "local" and not loc.path:
            loc.kind = "default"
        return loc

    def validate(self) -> str | None:
        """Error text, or None. Resolves the folder and (ssh) learns the remote's tools."""
        if self.kind == "local":
            p = Path(os.path.expanduser(self.path)).resolve()
            if not p.is_dir():
                return f"folder {p} does not exist"
            self.path = str(p)
        elif self.kind == "ssh":
            if not self.host:
                return "no SSH host given"
            r = probe(self.host, self.path or "~")
            if not r["ok"]:
                return r["error"]
            self.path, self.home, self.bins = r["path"], r["home"], r["bins"]
        return None

    def label(self) -> str:
        return {"local": self.path, "ssh": f"{self.host}:{self.path}"}.get(self.kind, "")

    def public(self) -> dict:
        return {"kind": self.kind, "path": self.path, "host": self.host, "label": self.label()}

    # ---------------- ssh session for the room
    @property
    def remote(self) -> bool:
        return self.kind == "ssh"

    @property
    def bridge(self) -> str:
        return f"{self.home}/.meetingroom/mcp_bridge.py"

    def connect(self, hub_port: int, token: str, tag: str = "") -> None:
        """Open the master connection with a reverse tunnel to the hub and install the bridge.
        `tag` (the room id) keeps two rooms on the same host on separate master connections."""
        self.cp = os.path.join(_SOCK_DIR, f"mr-{os.getpid()}{'-' + tag if tag else ''}-%C")
        err = ""
        for _ in range(6):
            port = random.randint(20000, 60000)
            r = subprocess.run(["ssh", *SSH_OPTS, "-o", "ControlMaster=yes", "-o", f"ControlPath={self.cp}",
                                "-o", "ControlPersist=yes", "-o", "ExitOnForwardFailure=yes",
                                "-R", f"127.0.0.1:{port}:127.0.0.1:{hub_port}", "-fN", self.host],
                               capture_output=True, text=True, timeout=40, stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                self.rport = port
                break
            err = r.stderr.strip()
        else:
            raise RuntimeError(f"could not open SSH tunnel to {self.host}: {err}")
        # bridge + per-run token, readable only by the remote user (the token never appears on a command line)
        put = "umask 077; mkdir -p ~/.meetingroom && cat > ~/.meetingroom/{}"
        for name, data in (("mcp_bridge.py", BRIDGE.read_text()), ("token", token)):
            r = _ssh(self.host, put.format(name), cp=self.cp, stdin=data)
            if r.returncode:
                raise RuntimeError(f"could not install the meeting bridge on {self.host}: {r.stderr.strip()}")

    def close(self) -> None:
        if self.remote and self.cp:
            subprocess.run(["ssh", "-o", f"ControlPath={self.cp}", "-O", "exit", self.host],
                           capture_output=True, timeout=10, stdin=subprocess.DEVNULL)

    def ssh_argv(self, agent: str, hub_port: int, exe: str, args: list[str], drop_key: str) -> list[str]:
        """Local argv that runs `exe args` in the project folder on the remote, wired to the hub."""
        env = (f"unset {drop_key}; export MR_URL=http://127.0.0.1:{self.rport}{self.url_base} MR_HOST=127.0.0.1:{hub_port} "
               f"MR_AGENT={shlex.quote(agent)} MR_UPLOAD=1 MCP_TOOL_TIMEOUT={24 * 3600 * 1000}; "
               "MR_TOKEN=$(cat ~/.meetingroom/token); export MR_TOKEN; ")
        bindir = shlex.quote(str(Path(exe).parent)) if exe.startswith("/") else "."
        env += f"export PATH={bindir}:$PATH; "   # npm/nvm shims need their sibling `node`
        script = f"cd -- {shlex.quote(self.path)} && {env}exec {shlex.join([exe, *args])}"
        return ["ssh", *SSH_OPTS, "-o", f"ControlPath={self.cp}", "-T", self.host, login_sh(script)]
