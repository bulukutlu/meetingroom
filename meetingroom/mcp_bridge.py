"""Tiny MCP server (stdio) that Claude Code agents load. It gives them:

  approve          – used as Claude Code's --permission-prompt-tool, so every
                     permission request becomes an approval card in the room
  share_to_screen  – put a file on the meeting's shared screen
  report_progress  – progress bar for long jobs
  wake_me          – be woken later (timer / file / process end) to report on background work
  say_now          – post an update mid-turn

It only talks to the meeting-room hub on 127.0.0.1. The hub address, the
per-run access token and the agent name arrive via environment variables
(never on the command line, never in a file).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request

URL = os.environ.get("MR_URL", "")
TOKEN = os.environ.get("MR_TOKEN", "")
AGENT = os.environ.get("MR_AGENT", "")
HOST = os.environ.get("MR_HOST", "")            # hub's Host header when reached through an SSH tunnel
UPLOAD = os.environ.get("MR_UPLOAD") == "1"     # remote agent: send file contents, the hub can't read our disk
MAX_UPLOAD = 50 * 1024 * 1024

TOOLS = [
    {
        "name": "approve",
        "description": "Permission gate handled by the meeting room host. Not for direct use.",
        "inputSchema": {
            "type": "object",
            "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                           "tool_use_id": {"type": "string"}},
            "required": ["tool_name", "input"],
        },
    },
    {
        "name": "report_progress",
        "description": (
            "Show a progress bar on the meeting's shared screen for a long job (expected > 5 minutes). "
            "Call at the start and at every stage change; call with done=true when finished."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"task": {"type": "string"}, "stage": {"type": "string"},
                           "step": {"type": "integer"}, "steps": {"type": "integer"},
                           "percent": {"type": "number"}, "eta_minutes": {"type": "number"}, "done": {"type": "boolean"}},
            "required": ["task"],
        },
    },
    {
        "name": "wake_me",
        "description": 'Ask the meeting room to wake you up later so you can speak again without being mentioned: use it after starting a long script/job, then end your turn. You get a new turn when ANY given condition is met: after_minutes elapsed, file_exists appears, or process pid_exited ends. note = what to check and report. Max 3 pending.',
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string"}, "after_minutes": {"type": "number"},
                           "file_exists": {"type": "string"}, "pid_exited": {"type": "integer"}},
            "required": ["note"],
        },
    },
    {
        "name": "say_now",
        "description": 'Post a short progress update to the meeting right now, in the middle of your turn, without ending it. Use for important milestones during long work.',
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "share_to_screen",
        "description": (
            "Show a file on the meeting's shared screen so everyone sees it. Supports images "
            "(png, jpg, svg, gif, webp), self-contained HTML pages, PDFs, and text/markdown/csv. "
            "Use absolute paths or paths relative to your working directory. "
            "Use paths instead of path to show multiple files together as a clickable folder."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "title": {"type": "string"},
                           "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100}},
            "anyOf": [{"required": ["path"]}, {"required": ["paths"]}],
        },
    },
]


def hub(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        URL + path, data=json.dumps({**payload, "agent": AGENT}).encode(),
        headers={"Content-Type": "application/json", "X-MR-Token": TOKEN, **({"Host": HOST} if HOST else {})}, method="POST",
    )
    # Proxies must never see this traffic; it is strictly local.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=None) as r:
        return json.loads(r.read())


def call(name: str, args: dict) -> str:
    if name == "approve":
        try:
            res = hub("/internal/permission", {"tool_name": args.get("tool_name"), "input": args.get("input") or {}})
        except Exception as e:
            return json.dumps({"behavior": "deny", "message": f"meeting room unreachable: {e}"})
        if res.get("allow"):
            return json.dumps({"behavior": "allow", "updatedInput": args.get("input") or {}})
        return json.dumps({"behavior": "deny", "message": "The meeting host denied this. Do not retry it unchanged."})
    if name == "report_progress":
        try:
            return hub("/internal/progress", args).get("text", "ok")
        except Exception as e:
            return f"error: {e}"
    if name in ("wake_me", "say_now"):
        try:
            return hub("/internal/wake" if name == "wake_me" else "/internal/say", args).get("text", "ok")
        except Exception as e:
            return f"error: {e}"
    if name == "share_to_screen":
        if "paths" in args:
            paths = args["paths"]
            if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or not all(isinstance(p, str) and p.strip() for p in paths):
                return "error: paths must contain 1–100 file paths"
            files = []
            total = 0
            for p in paths:
                path = os.path.abspath(os.path.expanduser(p))
                if not os.path.isfile(path):
                    return f"error: {path} does not exist"
                total += os.path.getsize(path)
                if UPLOAD and total > MAX_UPLOAD:
                    return "error: combined files are larger than 50 MB"
                files.append({"path": path})
            if UPLOAD:
                for item in files:
                    with open(item["path"], "rb") as f:
                        item["content_b64"] = base64.b64encode(f.read()).decode()
            try:
                return hub("/internal/share", {"files": files, "title": args.get("title") or "Outputs"}).get("text", "shared")
            except Exception as e:
                return f"error: {e}"
        path = os.path.abspath(os.path.expanduser(args.get("path", "")))
        body = {"path": path, "title": args.get("title") or ""}
        if UPLOAD:
            if not os.path.isfile(path):
                return f"error: {path} does not exist"
            if os.path.getsize(path) > MAX_UPLOAD:
                return f"error: {path} is larger than 50 MB"
            with open(path, "rb") as f:
                body["content_b64"] = base64.b64encode(f.read()).decode()
        try:
            return hub("/internal/share", body).get("text", "shared")
        except Exception as e:
            return f"error: {e}"
    return f"unknown tool {name}"


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:  # notification
            continue
        if method == "initialize":
            result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "meetingroom", "version": "0.2"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params", {})
            result = {"content": [{"type": "text", "text": call(p.get("name"), p.get("arguments") or {})}]}
        elif method == "ping":
            result = {}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                         "error": {"code": -32601, "message": "method not found"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
