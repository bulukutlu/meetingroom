"""Tools the agents can call. Everything runs on YOUR machine, inside the
agent's working folder by default, and (in 'ask' mode) only after you approve
it in the meeting room."""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import tempfile
from itertools import islice
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
        "description": "Read a text file in pages (default 200 lines). Use offset and limit for specific sections. Relative paths are inside your workspace.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "Zero-based starting line (default 0).", "minimum": 0},
                "limit": {"type": "integer", "description": "Maximum lines to read (default 200, maximum 2000).", "minimum": 1, "maximum": 2000},
            },
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
        "name": "wake_me",
        "description": 'Ask the meeting room to wake you up later so you can speak again without being mentioned: use it after starting a long script/job, then end your turn. You get a new turn when ANY given condition is met: after_minutes elapsed, file_exists appears, or process pid_exited ends. note = what to check and report. Max 3 pending.',
        "schema": {"type": "object", "properties": {"note": {"type": "string"}, "after_minutes": {"type": "number"},
                   "file_exists": {"type": "string"}, "pid_exited": {"type": "integer"}}, "required": ["note"]},
    },
    {
        "name": "say_now",
        "description": 'Post a short progress update to the meeting right now, in the middle of your turn, without ending it. Use for important milestones during long work.',
        "schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "report_progress",
        "description": (
            "Show a progress bar on the meeting's shared screen for a long job (expected > 5 minutes). "
            "Call at the start and at every stage change; call with done=true when finished."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Short title of the long job."},
                "stage": {"type": "string", "description": "What is happening now, a few words."},
                "step": {"type": "integer"}, "steps": {"type": "integer", "description": "Total stages."},
                "percent": {"type": "number", "description": "0-100; optional if step/steps given."},
                "eta_minutes": {"type": "number", "description": "Estimated minutes remaining."},
                "done": {"type": "boolean"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "share_to_screen",
        "description": (
            "Put a file on the meeting's shared screen so everyone sees it. Supports images "
            "(png, jpg, svg, gif, webp), self-contained HTML pages, PDFs, and text/markdown/csv. "
            "HTML must be self-contained (inline assets or CDN links). "
            "Use paths instead of path to show multiple outputs together as a clickable folder."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100},
                "title": {"type": "string", "description": "Short caption shown above it."},
            },
            "anyOf": [{"required": ["path"]}, {"required": ["paths"]}],
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
    if name in ("read_file", "write_file", "list_dir", "share_to_screen", "report_progress"):
        if name == "share_to_screen" and "paths" in args:
            return any(not inside(workdir, resolve(workdir, p)) for p in args["paths"])
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
    return f"{name} {args.get('paths', args.get('path', ''))}"


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
            offset, limit = int(args.get("offset", 0)), int(args.get("limit", 200))
            if offset < 0 or not 1 <= limit <= 2000:
                return "error: offset must be >= 0 and limit must be between 1 and 2000"
            with p.open(encoding="utf-8", errors="replace") as f:
                lines = list(islice(f, offset, offset + limit + 1))
            text = _clip("".join(lines[:limit]))
            if len(lines) > limit:
                text += f"\n[more lines: read_file with offset={offset + limit}]"
            return text
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
            if "paths" in args:
                paths = args["paths"]
                if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or not all(isinstance(p, str) and p.strip() for p in paths):
                    return "error: paths must contain 1–100 file paths"
                files = [resolve(workdir, p) for p in paths]
                if any(not p.is_file() for p in files):
                    return "error: every shared path must be an existing file"
                return await share_cb(files, args.get("title") or "Outputs")
            p = resolve(workdir, args["path"])
            if not p.is_file():
                return f"error: {p} does not exist"
            return await share_cb(p, args.get("title") or p.name)
        return f"error: unknown tool {name}"
    except Exception as e:  # report errors to the model instead of crashing
        return f"error: {type(e).__name__}: {e}"


def machine_info(python: str) -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()}), python: {python}"
