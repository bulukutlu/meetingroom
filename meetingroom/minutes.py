"""Behind-the-scenes record and meeting minutes.

Spoken replies are kept short, so everything an agent does during a turn
(the prompt it got, its intermediate thoughts, every tool call with its full
input and output, files it shared, the final reply, PASSes, errors) is
appended to meetings/<session>/details.jsonl.

minutes.md is rebuilt from transcript.jsonl + details.jsonl after every turn
and when the app shuts down, so it is always up to date even if the app is
killed. Regenerate for an old session with:
    python -m meetingroom minutes ~/MeetingRoom/meetings/<session>
"""
from __future__ import annotations

import json
import time
from pathlib import Path

MAX_STORED = 20000      # chars kept per event in details.jsonl
MAX_IN_MINUTES = 1500   # chars of tool output shown in minutes.md


class Recorder:
    def __init__(self, session_dir: Path):
        self.path = session_dir / "details.jsonl"

    def write(self, agent: str, kind: str, text: str = "", turn: str | None = None, **extra):
        ev = {"ts": time.time(), "agent": agent, "turn": turn, "kind": kind,
              "text": _clip(str(text or ""), MAX_STORED), **extra}
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        except OSError:
            pass


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + f"\n… [{len(s) - n} more chars]"


def _load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _t(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _fence(s: str, lang: str = "") -> str:
    s = s.rstrip()
    tick = "````" if "```" in s else "```"
    return f"{tick}{lang}\n{s}\n{tick}"


def _quote(s: str) -> str:
    return "\n".join("> " + ln for ln in s.strip().splitlines())


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def _embed(e: dict) -> list[str]:
    """Image shares are embedded (from the session's shared/ copy, so the
    minutes stay valid even if the agent later overwrites the file); other
    files become links."""
    rel = e.get("copy") or e.get("text", "")
    title = e.get("title") or Path(rel).name
    if Path(rel).suffix.lower() in IMAGE_EXT:
        return [f"![{title}]({rel.replace(' ', '%20')})", f"*{title}* – @{e['agent']}, {_t(e['ts'])}", ""]
    return [f"📎 [{title}]({rel.replace(' ', '%20')}) – @{e['agent']}, {_t(e['ts'])}", ""]


def _render_turn(evs: list[dict], reply: str) -> list[str]:
    lines = []
    for e in evs:
        k, txt = e["kind"], e.get("text", "")
        if k == "thought" and txt.strip() and txt.strip() != reply.strip():
            lines.append(f"- *{_t(e['ts'])} thinking:* " + txt.strip().replace("\n", "\n  "))
        elif k == "tool_call":
            lines.append(f"- *{_t(e['ts'])}* **{e.get('tool', 'tool')}**\n\n" +
                         "\n".join("  " + ln for ln in _fence(txt).splitlines()))
        elif k == "tool_result" and txt.strip():
            lines.append("  - result:\n\n" +
                         "\n".join("    " + ln for ln in _fence(_clip(txt, MAX_IN_MINUTES)).splitlines()))
        elif k == "share":
            lines.append(f"- *{_t(e['ts'])}* shared on screen: **{e.get('title') or ''}** (`{txt}`)")
        elif k == "error":
            lines.append(f"- *{_t(e['ts'])}* **error:** {txt}")
        elif k == "stopped":
            lines.append(f"- *{_t(e['ts'])}* stopped by user")
    return lines


def build(session_dir: Path) -> Path:
    session_dir = Path(session_dir)
    msgs = _load(session_dir / "transcript.jsonl")
    det = _load(session_dir / "details.jsonl")
    by_turn: dict[str, list[dict]] = {}
    for e in det:
        if e.get("turn"):
            by_turn.setdefault(e["turn"], []).append(e)
    replied = {m.get("turn") for m in msgs if m.get("turn")}
    agents = sorted({e["agent"] for e in det} | {m["from"] for m in msgs if m.get("turn")})
    shares = [e for e in det if e["kind"] == "share"]
    start = min([m["ts"] for m in msgs] + [e["ts"] for e in det] or [time.time()])

    out = [f"# Meeting minutes – {session_dir.name}", "",
           f"*{time.strftime('%Y-%m-%d %H:%M', time.localtime(start))}, generated {time.strftime('%H:%M:%S')}*", "",
           f"**AI participants:** {', '.join('@' + a for a in agents) or '–'}", ""]
    if shares:
        out += ["## Shown on screen", ""]
        out += [f"- {_t(e['ts'])} @{e['agent']}: **{e.get('title') or ''}** – `{e['text']}`" for e in shares]
        out.append("")

    # Timeline: transcript messages, plus silent turns (PASS / error) that still did work.
    items = [("msg", m["ts"], m) for m in msgs if m.get("kind") != "note"]
    for tid, evs in by_turn.items():
        if tid not in replied and any(e["kind"] in ("tool_call", "share", "error", "stopped") for e in evs):
            items.append(("silent", evs[-1]["ts"], evs))
    items.sort(key=lambda x: x[1])

    out += ["## Discussion and work log", ""]
    for typ, ts, obj in items:
        if typ == "msg":
            m = obj
            tag = " (system)" if m.get("kind") == "system" else ""
            out += [f"**[{_t(ts)}] {m['from']}{tag}:**", "", _quote(m["text"]) or "> –", ""]
            evs = by_turn.get(m.get("turn"), []) if m.get("turn") else []
            for e in evs:
                if e["kind"] == "share":
                    out += _embed(e)
            work = _render_turn(evs, m["text"])
            if work:
                out += [f"<details><summary>Behind the scenes – @{m['from']}</summary>", "", *work, "", "</details>", ""]
        else:
            evs = obj
            out += [f"**[{_t(ts)}] @{evs[0]['agent']}** worked without posting a reply:", "",
                    *_render_turn(evs, ""), ""]
            for e in evs:
                if e["kind"] == "share":
                    out += _embed(e)
    p = session_dir / "minutes.md"
    p.write_text("\n".join(out), encoding="utf-8")
    return p
