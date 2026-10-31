"""Tools the agents can call. Everything runs on YOUR machine, inside the
agent's working folder by default, and (in 'ask' mode) only after you approve
it in the meeting room."""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import tempfile
from pathlib import Path

MAX_OUT = 20_000

TOOL_SPECS = [
    {
        "name": "run_shell",
        "description": (
            "Run a shell command on the user's local machine. Working directory is your "
            "workspace folder unless you cd elsewhere. Returns combined stdout/stderr and exit code."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command line to run."},
                "timeout_s": {"type": "integer", "description": "Timeout in seconds (default 600)."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "run_python",
        "description": (
            "Run a Python script on the user's machine (in your workspace folder). Use it for "
            "analysis and plotting; save figures to files (e.g. plt.savefig('fig.png', dpi=150)) "
            "and then call share_to_screen. Never call plt.show()."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Complete Python source."},
                "timeout_s": {"type": "integer", "description": "Timeout in seconds (default 600)."},
            },
            "required": ["code"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file (relative paths are inside your workspace).",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a text file (relative paths are inside your workspace).",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory (relative paths are inside your workspace).",
        "schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory, default '.'"}},
        },
    },
    {
        "name": "share_to_screen",
        "description": (
            "Put a file on the meeting's shared screen so everyone sees it. Supports images "
            "(png, jpg, svg, gif, webp), self-contained HTML pages, PDFs, and text/markdown/csv. "
            "HTML must be self-contained (inline assets or CDN links)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "title": {"type": "string", "description": "Short caption shown above it."},
            },
            "required": ["path"],
        },
    },
]

# Tools that always need approval in 'ask' mode.
EXEC_TOOLS = {"run_shell", "run_python"}


def anthropic_tools():
    return [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in TOOL_SPECS]


def openai_tools():
    return [
        {"type": "function", "name": t["name"], "description": t["description"],
         "parameters": t["schema"], "strict": False}
        for t in TOOL_SPECS
    ]


def resolve(workdir: Path, p: str | None) -> Path:
    p = (p or ".").strip()
    path = Path(os.path.expanduser(p))
    if not path.is_absolute():
        path = workdir / path
    return path.resolve()


def inside(workdir: Path, path: Path) -> bool:
    try:
        path.relative_to(workdir.resolve())
        return True
    except ValueError:
        return False


def needs_approval(name: str, args: dict, workdir: Path) -> bool:
    if name in EXEC_TOOLS:
        return True
    if name in ("read_file", "write_file", "list_dir", "share_to_screen"):
        return not inside(workdir, resolve(workdir, args.get("path")))
    return False


def describe(name: str, args: dict) -> str:
    if name == "run_shell":
        return args.get("command", "")
    if name == "run_python":
        return args.get("code", "")
    if name == "write_file":
        c = args.get("content", "")
        return f"write {args.get('path')} ({len(c)} chars)\n\n" + c[:1500]
    return f"{name} {args.get('path', '')}"


def _clip(s: str) -> str:
    if len(s) <= MAX_OUT:
        return s
    h = MAX_OUT // 2
    return s[:h] + f"\n\n… [{len(s) - MAX_OUT} chars omitted] …\n\n" + s[-h:]


async def _run_process(cmd, cwd: Path, timeout: int, shell: bool) -> str:
    holder: dict = {}

    def target():
        p = subprocess.Popen(cmd, cwd=str(cwd), shell=shell, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        holder["p"] = p
        try:
            out, _ = p.communicate(timeout=timeout)
            return p.returncode, out
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
            return -9, (out or "") + f"\n[timed out after {timeout}s]"

    try:
        code, out = await asyncio.to_thread(target)
    except asyncio.CancelledError:
        p = holder.get("p")
        if p and p.poll() is None:
            p.kill()
        raise
    return _clip(f"exit code: {code}\n{out}")


async def execute(name: str, args: dict, workdir: Path, python: str, share_cb) -> str:
    try:
        if name == "run_shell":
            return await _run_process(args["command"], workdir, int(args.get("timeout_s") or 600), True)
        if name == "run_python":
            fd, tmp = tempfile.mkstemp(suffix=".py", prefix="snippet_", dir=str(workdir))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(args["code"])
            try:
                return await _run_process([python, tmp], workdir, int(args.get("timeout_s") or 600), False)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if name == "read_file":
            p = resolve(workdir, args["path"])
            return _clip(p.read_text(encoding="utf-8", errors="replace"))
        if name == "write_file":
            p = resolve(workdir, args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"wrote {p} ({len(args['content'])} chars)"
        if name == "list_dir":
            p = resolve(workdir, args.get("path"))
            rows = []
            for c in sorted(p.iterdir())[:500]:
                rows.append(("d " if c.is_dir() else "f ") + c.name + ("" if c.is_dir() else f"  ({c.stat().st_size} B)"))
            return f"{p}\n" + "\n".join(rows)
        if name == "share_to_screen":
            p = resolve(workdir, args["path"])
            if not p.is_file():
                return f"error: {p} does not exist"
            return await share_cb(p, args.get("title") or p.name)
        return f"error: unknown tool {name}"
    except Exception as e:  # report errors to the model instead of crashing
        return f"error: {type(e).__name__}: {e}"


def machine_info(python: str) -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()}), python: {python}"
