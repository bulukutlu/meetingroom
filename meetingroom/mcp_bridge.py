"""Tiny MCP server (stdio) that Claude Code agents load. It gives them:

  approve          – used as Claude Code's --permission-prompt-tool, so every
                     permission request becomes an approval card in the room
  share_to_screen  – put a file on the meeting's shared screen

It only talks to the meeting-room hub on 127.0.0.1. The hub address, the
per-run access token and the agent name arrive via environment variables
(never on the command line, never in a file).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = os.environ.get("MR_URL", "")
TOKEN = os.environ.get("MR_TOKEN", "")
AGENT = os.environ.get("MR_AGENT", "")

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
        "name": "share_to_screen",
        "description": (
            "Show a file on the meeting's shared screen so everyone sees it. Supports images "
            "(png, jpg, svg, gif, webp), self-contained HTML pages, PDFs, and text/markdown/csv. "
            "Use absolute paths or paths relative to your working directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "title": {"type": "string"}},
            "required": ["path"],
        },
    },
]


def hub(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        URL + path, data=json.dumps({**payload, "agent": AGENT}).encode(),
        headers={"Content-Type": "application/json", "X-MR-Token": TOKEN}, method="POST",
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
    if name == "share_to_screen":
        path = os.path.abspath(os.path.expanduser(args.get("path", "")))
        try:
            return hub("/internal/share", {"path": path, "title": args.get("title") or ""}).get("text", "shared")
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
