"""Agents: one asyncio worker per participant, each with a provider backend
(Anthropic Messages API, OpenAI Responses API, or a key-free demo backend)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from . import annotate, tools
from .keys import get_key
from .minutes import build as build_minutes

BRIDGE = str(Path(__file__).with_name("mcp_bridge.py"))

# Fixed face per agent, chosen by model seniority (stronger model = older face),
# so a character never changes with how many agents are loaded or their order.
# Faces in static/faces, by apparent age: 1 (~20) < 2 (~30) < 4 (~35) < 6 (~40) < 5 (~50) < 3 (~60).
# Anthropic line uses the men 4/6/3, OpenAI line the women 1/2/5, so the two
# families never collide. Override per agent with `face:` in agents.yaml.
FACE_BY_TIER = {
    "anthropic": {0: 4, 1: 6, 2: 3},   # haiku, sonnet, opus/fable
    "openai":    {0: 1, 1: 2, 2: 5},   # nano, mini, full / codex default
}


def default_face(provider: str, model: str | None) -> int:
    m = (model or "").lower()
    if provider in ("claude-code", "anthropic"):
        tier = 0 if "haiku" in m else 1 if "sonnet" in m else 2   # opus, fable, unknown -> senior
        return FACE_BY_TIER["anthropic"][tier]
    if provider in ("codex", "openai"):
        tier = 0 if "nano" in m else 1 if ("mini" in m or "spark" in m) else 2
        return FACE_BY_TIER["openai"][tier]
    return 4


def agent_face(spec: dict) -> int:
    if spec.get("face"):
        return int(spec["face"])
    prov = spec.get("provider", "mock")
    if prov == "mock":   # demo agents: guess the family from the name
        n = spec.get("name", "").lower()
        prov = "openai" if any(k in n for k in ("gpt", "codex", "openai")) else "anthropic"
        return default_face(prov, n if any(k in n for k in ("haiku", "sonnet", "mini", "nano")) else "")
    return default_face(prov, spec.get("model"))


class TokenLimitReached(RuntimeError):
    """A provider stopped the turn because its token allowance was exhausted."""


def is_token_limit(error) -> bool:
    text = str(error).lower()
    return isinstance(error, TokenLimitReached) or any(marker in text for marker in (
        "insufficient_quota", "usage_limit_reached", "rate_limit_exceeded",
        "rate_limit_error", "ratelimiterror", "rate limit reached", "rate limit exceeded",
        "usage limit reached", "usage limit exceeded", "you've hit your limit",
        "you have hit your limit", "you've reached your usage limit",
        "out of tokens", "token limit", "max_tokens", "max_output_tokens",
        "credit balance is too low", "quota exceeded", "quota has been exceeded",
        "context_length_exceeded", "maximum context length",
    ))


# Faces by apparent gender (see static/faces); names and Kokoro voices follow the face so all three agree.
FACE_GENDER = {1: "f", 2: "f", 5: "f", 3: "m", 4: "m", 6: "m", 7: "f", 8: "m", 9: "m", 10: "f", 11: "m", 12: "f", 13: "f"}
CLONE_FACES = [4, 6, 3, 1, 2, 5, 8, 9, 11, 7, 10, 12, 13]
FEMALE_CLONE_FACES = [1, 2, 5, 7, 10, 12, 13]   # OpenAI agents are always female
# Names per model family and tier (0 small, 1 mid, 2 large), per gender. Override with `person:` in agents.yaml.
NAMES = {
    ("anthropic", 0): {"m": ["Rafael", "Tomasz", "Hiro", "Lucas"], "f": ["Amara", "Nadia", "Chiara", "Freya"]},
    ("anthropic", 1): {"m": ["Mateo", "Omar", "Pavel", "Dmitri"], "f": ["Priya", "Leila", "Elena", "Zainab"]},
    ("anthropic", 2): {"m": ["Alejandro", "Kenji", "Henrik", "Matthias"], "f": ["Sofia", "Katarina", "Imani", "Greta"]},
    ("openai", 0): {"f": ["Mei", "Yara", "Ottilie", "Bianca", "Anneli", "Rosa"]},
    ("openai", 1): {"f": ["Sunniva", "Camila", "Aiko", "Liv", "Marta", "Selma"]},
    ("openai", 2): {"f": ["Helga", "Ingrid", "Margarethe", "Noor", "Valentina", "Astrid"]},
}
# Kokoro voices by gender, handed out in order so loaded agents sound different.
VOICES = {"m": ["am_michael", "bm_george", "am_adam", "am_puck", "bm_daniel", "am_eric", "am_liam"],
          "f": ["af_heart", "bf_emma", "af_nicole", "bf_isabella", "af_bella"]}


def agent_family_tier(spec: dict) -> tuple[str, int]:
    prov = spec.get("provider", "mock")
    m = (spec.get("model") or "").lower()
    if prov == "mock":
        n = spec.get("name", "").lower()
        prov = "openai" if any(k in n for k in ("gpt", "codex", "openai")) else "anthropic"
        m = n
    if prov in ("codex", "openai"):
        return "openai", 0 if "nano" in m else 1 if ("mini" in m or "spark" in m) else 2
    return "anthropic", 0 if "haiku" in m else 1 if "sonnet" in m else 2


def agent_gender(spec: dict) -> str:
    return FACE_GENDER.get(agent_face(spec), "m")


def assign_people(specs: list[dict]) -> list[dict]:
    """Give every spec a unique `person` matching its face's gender and its model type; explicit ones are kept."""
    used = {str(s["person"]).lower() for s in specs if s.get("person")}
    handles = {s["name"].lower() for s in specs}
    for s in specs:
        if s.get("person"):
            continue
        fam, tier = agent_family_tier(s)
        g = agent_gender(s) if fam == "anthropic" else "f"
        order = [NAMES[(fam, tier)][g]] + [NAMES[(fam, t)][g] for t in (2, 1, 0) if t != tier]
        pick = next((n for pool in order for n in pool if n.lower() not in used and n.lower() not in handles), None)
        s["person"] = pick or f"Agent{len(used) + 1}"
        used.add(s["person"].lower())
    return specs


def assign_voices(specs: list[dict]) -> dict[str, str]:
    """agent name -> Kokoro voice, always of the same gender as the agent's face."""
    taken = {s["voice"] for s in specs if s.get("voice")}
    nxt = {"m": 0, "f": 0}
    out = {}
    for s in specs:
        if s.get("voice"):
            out[s["name"].lower()] = s["voice"]
            continue
        g = agent_gender(s)
        pool = VOICES[g]
        free = [v for v in pool if v not in taken] or pool
        v = free[nxt[g] % len(free)] if free is pool else free[0]
        nxt[g] += 1
        taken.add(v)
        out[s["name"].lower()] = v
    return out


MAX_COPIES = 4


def _face_for_clone(base_spec: dict, i: int) -> int:
    if agent_family_tier(base_spec)[0] == "openai":   # OpenAI agents are always female
        return FEMALE_CLONE_FACES[(i - 2) % len(FEMALE_CLONE_FACES)]
    f = agent_face(base_spec)
    return CLONE_FACES[(i + CLONE_FACES.index(f) - 1) % len(CLONE_FACES)] if f in CLONE_FACES else (i % 6) + 1


def _expand(base: list[dict], wanted: list[str]) -> list[dict]:
    by = {a["name"].lower(): a for a in base}
    out: list[dict] = []
    count: dict[str, int] = {}
    for w in wanted:
        k = w.lower()
        explicit = 0
        if k in by:
            root = k
        else:
            m = re.fullmatch(r"(.+?)[-_ ]?(\d+)", k)
            root = m.group(1) if m else k
            explicit = int(m.group(2)) if m else 0
        if root not in by:
            continue
        spec = dict(by[root])
        n = 1 if explicit else count.get(root, 0) + 1
        if not explicit:
            count[root] = n
        taken = {s["name"].lower() for s in out}
        i = 0
        if explicit > 1 and f"{root}-{explicit}" not in taken:
            i = explicit
        elif n > 1 or (k in taken):
            i = 2
            while f"{root}-{i}" in taken or f"{root}-{i}" in by:
                i += 1
        if i:
            spec["name"] = f"{root}-{i}"
            spec.pop("person", None)
            spec["face"] = _face_for_clone(by[root], i)
            spec.pop("voice", None)
        out.append(spec)
    return assign_people(out)


def instance_table(base: list[dict]) -> list[dict]:
    """Every seat a model can fill (handle, name, face, colour), the same whichever seats are chosen."""
    return _expand(base, [a["name"] for a in base for _ in range(MAX_COPIES)])


def expand_agents(base: list[dict], wanted: list[str]) -> list[dict]:
    """Specs for the wanted handles. `sonnet-2` style handles (or a handle named again) are clones of
    their base spec with the same shirt colour and their own face and name, fixed per handle."""
    fixed = {s["name"].lower(): s.get("person") for s in instance_table(base)}
    out = _expand(base, wanted)
    for s in out:
        if s["name"].lower() in fixed and not re.fullmatch(r"[^\d]+", s["name"]) :
            s["person"] = fixed[s["name"].lower()]
    return out


def shade(hexcol: str, k: int) -> str:
    """Same hue family, shifted lightness, so clones are distinguishable at a glance."""
    import colorsys
    try:
        r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except Exception:
        return hexcol
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    l = min(0.8, max(0.3, l + (0.12 if k % 2 else -0.12) * ((k + 1) // 2)))
    h = (h + 0.04 * k) % 1
    r, g, b = colorsys.hls_to_rgb(h, l, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


MAX_STEPS = 40  # tool-use iterations per turn

# Shared by every agent type. The point of the room is that it feels FASTER
# than chatting, so replies must be minimal.
MEETING_RULES = """MEETING RULES (they override your usual style):
- Speak only when it is unmistakably your turn: you were addressed by @name (or @all) with something to do or answer. If you are unsure, or have nothing that changes anything, reply exactly: PASS  (it is not shown to anyone).
- Your reply is read aloud in a live meeting where everyone can see the shared screen. Match the length to what was asked:
  * Task where you put something on the shared screen ("plot X", "make a table"): reply "Here it is." and stop. Say "Here it is" ONLY when you actually showed something on screen; otherwise just give the answer or result directly, with no such opener. Add ONE short sentence only if there is a caveat or hidden decision the listener truly needs (e.g. "Here it is. I dropped the first 200 events, they were pre-calibration."). Hard limit: 25 words. No lists, no file names, no recap of what you changed.
  * Quick question (yes/no, a number, a fact): answer in at most 10 words. "Yes." / "62 electrons."
  * Explicit request to explain, discuss or go into detail: answer as fully as needed, but still as tight as possible. Long spoken explanations are fine here; put equations, tables or code on screen.
- Default to the shortest reply that works. If in doubt, cut it in half. Every spoken sentence costs the room time.
- Prefer showing over telling: results, numbers, comparisons, tables and code belong on the shared screen (plots as PNG, tables/notes as markdown .md files which render nicely, interactive things as self-contained HTML).
- Never: greetings, pleasantries, thanks, restating the question, announcing routine actions, step-by-step narration of routine actions, offering further help, "standing by", "ready when you are", summarising what others said, replying to acknowledgements.
- Exception, big tasks: before starting a long project (many steps, minutes of work), give ONE short heads-up sentence saying what you will do (e.g. "I'll refactor the parser and rerun all fits."). Do not wait for a reply; start working right away. Never do this for routine or quick tasks.
- Do not answer for others or comment on messages addressed to someone else.
- Lines starting "↳ points at" are marks the host drew on the shared screen: they say exactly which part of what was shown (text quoted verbatim, page/lines, or a small region image) the message is about. Act on that part; open a region image only when the quoted text isn't enough.
- Hand work to another participant only when needed, by STARTING your reply with their @handle (shown in the roster) and the concrete task (e.g. "@sonnet plot thr_map.csv as a heatmap."). To hand tasks to several people, start each sentence or line with its @handle (e.g. "@sonnet plot X. @codex check Y."). The room also accepts their first name as @Name. People may call you by your first name too. An @handle in the middle of a sentence does nothing; refer to others without @ otherwise.
"""
TURN_REMINDER = ("REMINDER: be as brief as possible. Task: show the result on screen, then \"Here it is.\" (only if you showed something on screen; otherwise just answer directly) plus at most ONE short "
                 "sentence for a caveat; max 25 words, no lists, no recap. Quick question: max 10 words. Never describe what is on "
                 "screen. Only go long when explicitly asked to explain. If nothing was asked of you, reply exactly: PASS")


# Reasoning-effort levels selectable per agent (applied from the next turn on).
EFFORTS = {
    "claude-code": ["low", "medium", "high", "xhigh", "max"],
    "codex": ["low", "medium", "high", "xhigh", "max"],
}


class Agent:
    def __init__(self, room, spec: dict):
        self.room = room
        self.spec = spec
        self.name: str = spec["name"]
        self.person: str = spec.get("person") or self.name.capitalize()
        self.provider: str = spec.get("provider", "mock")
        self.model: str = spec.get("model", "")
        self.color: str = spec.get("color", "#8888ff")
        self.role: str = spec.get("role", "")
        self.approval: str = spec.get("approval", "ask")  # 'ask' or 'auto'
        self.supervisor: bool = bool(spec.get("supervisor", False))  # may run longer back-and-forth chains
        # Reasoning effort; medium unless agents.yaml says otherwise (changeable live in the room).
        self.effort: str = str(spec.get("effort") or ("medium" if self.provider in EFFORTS else ""))
        self.max_tokens: int = int(spec.get("max_tokens", 16000))
        loc = room.location
        # local project folder: everyone works there; otherwise each agent has its own folder
        # (for SSH rooms that local folder only serves API/demo agents, CLI agents run remotely)
        self.workdir: Path = Path(loc.path) if loc.kind == "local" else (room.workspace / "agents" / self.name).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.status = "idle"
        self.activity = ""
        self.seen = 0              # index into room.messages already given to this agent
        self.pending_context = ""  # context not yet committed (kept if a turn fails)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.requesters: set[str] = set()   # agents who handed work to this one since its last turn
        self.current: asyncio.Task | None = None
        self.backend = None
        self.offline_reason = ""
        self.usage: dict = {}      # last-turn token usage + cumulative cost (Claude Code agents)
        self.turn_id: str | None = None
        try:
            self.backend = make_backend(self)
        except Exception as e:
            self.offline_reason = str(e)
            self.status = "offline"

    # ---------- presentation ----------
    def public(self) -> dict:
        return {
            "name": self.name, "person": self.person, "provider": self.provider, "model": self.model,
            "color": self.color, "role": self.role, "status": self.status,
            "activity": self.activity, "approval": self.approval, "supervisor": self.supervisor,
            "effort": self.effort, "efforts": EFFORTS.get(self.provider, []),
            "offline_reason": self.offline_reason, "workdir": self.where(),
            "face": agent_face(self.spec), "usage": self.usage,
        }

    @property
    def remote(self) -> bool:
        """Runs on the SSH machine (only the CLI agents can)."""
        return self.room.location.remote and self.provider in ("claude-code", "codex")

    def where(self) -> str:
        loc = self.room.location
        return f"{loc.host}:{loc.path}" if self.remote else str(self.workdir)

    def trace(self, kind: str, text: str = "", **extra):
        """Record behind-the-scenes work for the meeting minutes."""
        self.room.recorder.write(self.name, kind, text, turn=self.turn_id, **extra)

    async def set_status(self, status: str | None = None, activity: str | None = None):
        if status is not None:
            self.status = status
        if activity is not None:
            self.activity = activity[:300]
        await self.room.broadcast({"type": "agent", "agent": self.public()})

    def system_prompt(self) -> str:
        others = [a for a in self.room.agents.values() if a.name != self.name]
        roster = "\n".join(f"- {a.person} (@{a.name}, {a.provider} {a.model}): {a.role or 'participant'}" for a in others) or "- (none)"
        return f"""You are {self.person} (@{self.name}), an AI participant in a live working meeting run from the meeting-room app on {self.room.user}'s computer.

Your role: {self.role or 'general assistant'}

Other AI participants:
{roster}

{MEETING_RULES}
How the meeting works:
- You receive new transcript lines since your last turn, then the request addressed to you. Your final text answer is posted to the meeting.
- You can actually do work on {self.room.user}'s machine with tools: run_shell, run_python, read_file, write_file, list_dir. Machine: {tools.machine_info(self.room.python)}.
- Your workspace folder is {self.workdir}. Relative paths resolve there. Files elsewhere may be accessed with absolute paths; {self.room.user} may be asked to approve.
{location_note(self)}- Show results with share_to_screen (plots as PNG/SVG, interactive pages as self-contained HTML, tables as CSV/markdown). Prefer showing over describing. For multiple related outputs, call share_to_screen with paths: ["plot.png", "summary.md"] and a title to show a clickable folder; use path for a single file.
- If a tool call is denied, do not retry it unchanged; adapt or ask.
- For any job you expect to take more than 5 minutes, call report_progress with task (short title), stage (what is happening now), step/steps or percent, and eta_minutes; update it at each stage and finish with done=true. It shows as a progress bar on the shared screen.
"""

    # ---------- turn handling ----------
    async def run_forever(self):
        while True:
            hop = await self.queue.get()
            while not self.queue.empty():  # coalesce bursts of mentions
                hop = min(hop, self.queue.get_nowait())
            if self.backend is None:
                await self.room.post("system", f"@{self.name} is offline: {self.offline_reason}", kind="system")
                continue
            self.current = asyncio.create_task(self._turn(hop))
            try:
                await self.current
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():  # app shutting down
                    raise
                self.trace("stopped")
                await self.set_status("idle", "stopped")
                await self.room.post(self.name, "_(stopped)_", kind="note")
            except Exception as e:
                self.trace("error", f"{type(e).__name__}: {e}")
                if is_token_limit(e):
                    await self.set_status("sleeping", "Token or usage limit reached. Mention me to retry when available.")
                    await self.room.post("system", f"@{self.name} is sleeping: {str(e)[:500]}", kind="system")
                else:
                    await self.set_status("idle", "error")
                    await self.room.post("system", f"@{self.name} hit an error: {type(e).__name__}: {e}", kind="system")
            finally:
                self.current = None
                self.turn_id = None
                try:
                    from .saved import checkpoint
                    checkpoint(self.room)
                    await asyncio.to_thread(build_minutes, self.room.session_dir)
                except Exception:
                    pass

    def stop(self):
        if self.current and not self.current.done():
            self.current.cancel()

    def _attachment_line(self, att: dict) -> str:
        """A file the user attached. Local agents get a copy inside their workspace (no approval needed to read it);
        remote (SSH) agents can't see this computer's disk, so text files are inlined and the rest is reported."""
        src = Path(att["path"])
        if self.remote:
            if att.get("image") or att["size"] > 200_000:
                return f"  (attached {att['name']}, {att['size']} bytes: not available over SSH; ask {self.room.user} to describe or paste it)"
            try:
                text = src.read_text(encoding="utf-8")
            except Exception:
                return f"  (attached {att['name']}: binary file, not available over SSH)"
            return f"  --- attached file {att['name']} ---\n{text}\n  --- end of {att['name']} ---"
        try:
            dest = self.workdir / "attachments" / f"{att['id']}_{att['name']}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copyfile(src, dest)
            path = dest
        except Exception:
            path = src
        kind = "image" if att.get("image") else "file"
        return f"  [attached {kind}: {path}  ({att['size']} bytes) - read it with your file tools]"

    def _gather_context(self) -> str:
        if getattr(self, "recovery_context", ""):
            self.pending_context = self.recovery_context + self.pending_context
            self.recovery_context = ""
        new = self.room.messages[self.seen:]
        self.seen = len(self.room.messages)
        lines = []
        for m in new:
            if m["from"] == self.name or m["kind"] == "note":
                continue
            t = time.strftime("%H:%M", time.localtime(m["ts"]))
            lines.append(f"[{t}] {m['from']}: {m['text']}")
            for an in m.get("anchors") or []:   # marks on the shared screen: text verbatim, visuals as a small crop
                lines.append(annotate.describe(an))
            for att in m.get("attachments") or []:
                lines.append(self._attachment_line(att))
        if lines:
            self.pending_context += "\n".join(lines) + "\n"
        return self.pending_context

    async def _turn(self, hop: int):
        ctx = self._gather_context()
        reqs = sorted(self.requesters)
        self.requesters = set()
        handle = " ".join(f"@{r}" for r in reqs)
        prompt = (
            "New in the meeting transcript:\n" + (ctx or "(nothing new)\n") +
            f"\nYou ({self.person}, @{self.name}) were mentioned. Do/answer only what was asked of YOU.\n\n{TURN_REMINDER}"
            + (f"\n\nYou were asked by {handle}: START your reply with {handle} so they are notified and can react." if reqs else "")
        )
        self.turn_id = uuid.uuid4().hex[:10]
        self.trace("prompt", prompt)
        await self.set_status("thinking", "Reviewing request…")
        reply = (await self.backend.turn(prompt) or "").strip()
        self.pending_context = ""
        await self.set_status("idle", "")
        await self.room.clear_progress(self)   # bars only live while the turn runs
        if reply.strip(" .*_`\"'").upper() in ("PASS", ""):
            self.trace("pass", reply)
            return  # nothing to say: stay silent
        for r in reqs:   # guarantee the requester is addressed, else they are never triggered again
            if not re.match(r"\s*(?:@[\w\-]+[\s,:]*)*?@" + re.escape(r) + r"\b", reply, re.I):
                reply = f"@{r} " + reply
        self.trace("reply", reply)
        await self.room.post(self.name, reply, hop=hop + 1, turn=self.turn_id)

    async def exec_tool(self, name: str, args: dict) -> str:
        if not isinstance(args, dict):
            args = {}
        summary = tools.describe(name, args)
        first = summary.splitlines()[0] if summary else name
        if self.approval == "ask" and tools.needs_approval(name, args, self.workdir):
            await self.set_status("waiting", f"waiting for approval: {name}")
            ok = await self.room.request_approval(self, name, summary)
            if not ok:
                await self.set_status("working", f"denied: {name}")
                return "The user DENIED this action. Do not retry it unchanged."
        if name == "report_progress":
            out = await self.room.report_progress(self, args)
            self.trace("tool_result", out, tool=name)
            return out
        await self.set_status("working", f"{name}: {first[:120]}")
        self.trace("tool_call", summary or json.dumps(args, indent=1), tool=name)
        out = await tools.execute(name, args, self.workdir, self.room.python,
                                  lambda p, title: self.room.share(self, p, title))
        self.trace("tool_result", out, tool=name)
        await self.set_status("thinking", f"Reviewing results: {name}")
        return out


# ---------------------------------------------------------------- backends

def make_backend(agent: Agent):
    if agent.provider == "claude-code":
        return ClaudeCodeBackend(agent)
    if agent.provider == "codex":
        return CodexBackend(agent)
    if agent.provider == "anthropic":
        return AnthropicBackend(agent)
    if agent.provider == "openai":
        return OpenAIBackend(agent)
    if agent.provider == "mock":
        return MockBackend(agent)
    raise ValueError(f"unknown provider '{agent.provider}'")


def location_note(a: Agent) -> str:
    """Tells every agent where this meeting's work happens."""
    loc = a.room.location
    if loc.kind == "local":
        return f"- PROJECT: this meeting works in the project folder {loc.path} (your working directory). Keep work and outputs there.\n"
    if loc.kind == "ssh" and a.remote:
        return (f"- PROJECT: this meeting works on the REMOTE machine '{loc.host}' in {loc.path}, reached over SSH. You are "
                f"running on {loc.host} in that folder; every command and file you touch is on {loc.host}, not on "
                f"{a.room.user}'s laptop. share_to_screen still works (files are uploaded to the room).\n")
    if loc.kind == "ssh":
        return (f"- PROJECT: this meeting's project lives on the REMOTE machine '{loc.host}' in {loc.path}. Your own tools run "
                f"locally; reach the project with run_shell and `ssh {loc.host} '<command>'` (copy results back with scp to share them).\n")
    return ""


def cli_meeting_prompt(a: Agent, tools_hint: str) -> str:
    """System text for the CLI-driven agents (Claude Code, Codex)."""
    others = [o for o in a.room.agents.values() if o.name != a.name]
    roster = ", ".join(f"{o.person} (@{o.name}, {o.role or o.model})" for o in others) or "none"
    return (
        f"You are {a.person} (@{a.name}), one participant in a live working meeting hosted by {a.room.user} "
        f"in the meeting-room app. Your role: {a.role or 'general assistant'}. Other AI participants: {roster}.\n\n"
        + MEETING_RULES + location_note(a) +
        "\nEach turn you get the new transcript lines and the request addressed to you. Do the work with your "
        "tools; your final text is posted to the meeting. " + tools_hint +
        '\nFor multiple related outputs, call share_to_screen with paths: ["plot.png", "summary.md"] '
        'and a title to show a clickable folder. Use path for a single file.'
        '\nFor any job you expect to take more than 5 minutes, call the meetingroom report_progress tool with task (short title), '
        'stage (what is happening now), step/steps or percent, and eta_minutes; update it at each stage and finish with done=true. '
        'It shows as a progress bar on the shared screen.'
    )


def bridge_env(a: Agent, drop_key: str) -> dict:
    """Environment for a CLI agent: tells the MCP bridge how to reach the hub and
    removes the API key variable so the CLI uses the user's own login."""
    env = dict(os.environ)
    env.update({"MR_URL": f"http://127.0.0.1:{a.room.port}{a.room.base}", "MR_TOKEN": a.room.token, "MR_AGENT": a.name,
                "MR_HOST": f"127.0.0.1:{a.room.port}", "MR_UPLOAD": "0"})
    env.pop(drop_key, None)
    return env


def _need_key(provider: str) -> str:
    key, _ = get_key(provider)
    if not key:
        raise RuntimeError(f"no {provider} API key (run: python -m meetingroom set-key {provider})")
    return key


class AnthropicBackend:
    def __init__(self, agent: Agent):
        from anthropic import AsyncAnthropic
        self.agent = agent
        self.client = AsyncAnthropic(api_key=_need_key("anthropic"))
        self.history: list = []

    async def turn(self, user_text: str) -> str:
        a = self.agent
        msgs = list(self.history) + [{"role": "user", "content": user_text}]
        for _ in range(MAX_STEPS):
            r = await self.client.messages.create(
                model=a.model, max_tokens=a.max_tokens, system=a.system_prompt(),
                tools=tools.anthropic_tools(), messages=msgs,
            )
            msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in r.content]})
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            if r.stop_reason == "max_tokens":
                self.history = msgs
                raise TokenLimitReached("Output token limit reached; mention me to continue.")
            if r.stop_reason != "tool_use":
                self.history = msgs
                return text
            if text:
                a.trace("thought", text)
                await a.set_status(activity=text[:200])
            results = []
            for b in r.content:
                if b.type == "tool_use":
                    out = await a.exec_tool(b.name, b.input)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            msgs.append({"role": "user", "content": results})
        self.history = msgs
        return "I hit my step limit for this request; tell me if I should continue."


class OpenAIBackend:
    """OpenAI Responses API (required for tool calling). store=False keeps
    conversation state on your machine rather than on OpenAI's servers."""

    def __init__(self, agent: Agent):
        from openai import AsyncOpenAI
        self.agent = agent
        self.client = AsyncOpenAI(api_key=_need_key("openai"))
        self.items: list = []
        self.include_reasoning = True

    async def _create(self, items):
        kw = dict(model=self.agent.model, instructions=self.agent.system_prompt(),
                  input=items, tools=tools.openai_tools(), store=False)
        if self.include_reasoning:
            try:
                return await self.client.responses.create(include=["reasoning.encrypted_content"], **kw)
            except Exception as e:
                if "include" not in str(e) and "reasoning" not in str(e):
                    raise
                self.include_reasoning = False  # non-reasoning model
        return await self.client.responses.create(**kw)

    async def turn(self, user_text: str) -> str:
        a = self.agent
        items = list(self.items) + [{"role": "user", "content": user_text}]
        for _ in range(MAX_STEPS):
            r = await self._create(items)
            for it in r.output:
                items.append(it.model_dump(exclude_none=True))
            if r.status == "incomplete" and getattr(r.incomplete_details, "reason", "") == "max_output_tokens":
                self.items = items
                raise TokenLimitReached("Output token limit reached; mention me to continue.")
            calls = [it for it in r.output if it.type == "function_call"]
            if not calls:
                self.items = items
                return r.output_text or ""
            for c in calls:
                try:
                    args = json.loads(c.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = await a.exec_tool(c.name, args)
                items.append({"type": "function_call_output", "call_id": c.call_id, "output": out})
        self.items = items
        return "I hit my step limit for this request; tell me if I should continue."


class ClaudeCodeBackend:
    """Drives your installed Claude Code CLI (`claude -p`), logged in with your
    own claude.ai account. The meeting room never sees those credentials:
    Claude Code keeps them in its own secure storage.

    Every turn runs `claude -p --resume <session>` in the agent's folder. Claude
    Code's permission prompts are answered by the meeting room (approval cards)
    through the local MCP bridge, which also provides share_to_screen."""

    def __init__(self, agent: Agent):
        self.agent = agent
        loc = agent.room.location
        exe = (agent.spec.get("remote_claude_path") or loc.bins.get("claude")) if agent.remote else find_claude(agent.spec.get("claude_path"))
        if not exe and agent.remote:
            raise RuntimeError(f"Claude Code not found on {loc.host}. Install it there and log in once (`claude`), "
                               "or set `remote_claude_path:` for this agent in agents.yaml.")
        if not exe:
            raise RuntimeError(
                "Claude Code not found. In your terminal run `which claude` (or `type claude`) and put "
                "that path as `claude_path:` for this agent in agents.yaml.")
        self.exe = exe
        self.session_id: str | None = None
        self.permission_mode = agent.spec.get("permission_mode")  # optional
        self.extra_dirs = [] if agent.remote else [str(Path(d).expanduser()) for d in agent.spec.get("add_dirs", [])]
        py, bridge = (loc.bins.get("python3"), loc.bridge) if agent.remote else (sys.executable, BRIDGE)
        self.mcp_config = json.dumps({"mcpServers": {"meetingroom": {
            "type": "stdio", "command": py, "args": [bridge],
        }}})

    def _meeting_prompt(self) -> str:
        return cli_meeting_prompt(self.agent,
            "Show results with the mcp__meetingroom__share_to_screen "
            "tool (plots as PNG/SVG, interactive pages as self-contained HTML, tables as CSV/markdown); show rather "
            "than describe. Save figures to files and never open GUI windows. If an action is denied, adapt instead "
            "of retrying unchanged.")

    def _cmd(self) -> list[str]:
        a = self.agent
        cmd = ["-p", "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", self._meeting_prompt(),
               "--mcp-config", self.mcp_config,
               "--permission-prompt-tool", "mcp__meetingroom__approve",
               "--allowedTools", "mcp__meetingroom__share_to_screen", "mcp__meetingroom__report_progress"]
        if a.model:
            cmd += ["--model", a.model]
        if a.effort:
            cmd += ["--effort", a.effort]
        if self.permission_mode:
            cmd += ["--permission-mode", self.permission_mode]
        for d in self.extra_dirs:
            cmd += ["--add-dir", d]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        if a.remote:
            return a.room.location.ssh_argv(a.name, a.room.port, self.exe, cmd, "ANTHROPIC_API_KEY")
        return [self.exe, *cmd]

    async def turn(self, user_text: str) -> str:
        try:
            return await self._run(user_text)
        except _ResumeFailed:
            self.session_id = None
            return await self._run(user_text)

    def _record_usage(self, ev: dict):
        """Keep the last turn's context size and a running cost total for the UI."""
        u = ev.get("usage") or {}
        a = self.agent
        ctx = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) \
            + int(u.get("cache_creation_input_tokens") or 0)
        a.usage = {
            "context_tokens": ctx,
            "output_tokens": int(u.get("output_tokens") or 0),
            "cost_usd": round(float(a.usage.get("cost_usd", 0)) + float(ev.get("total_cost_usd") or 0), 4),
            "turns": int(a.usage.get("turns", 0)) + 1,
        }

    async def _run(self, user_text: str) -> str:
        a = self.agent
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        env = bridge_env(a, "ANTHROPIC_API_KEY")  # Claude Code uses YOUR claude.ai login
        env["MCP_TOOL_TIMEOUT"] = str(24 * 3600 * 1000)
        proc = subprocess.Popen(self._cmd(), cwd=str(a.workdir), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
        stderr_tail: deque[str] = deque(maxlen=30)

        def pump_out():
            for line in proc.stdout:
                loop.call_soon_threadsafe(q.put_nowait, line)
            loop.call_soon_threadsafe(q.put_nowait, None)

        def pump_err():
            stderr_tail.extend(proc.stderr)

        threading.Thread(target=pump_out, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()
        try:
            proc.stdin.write(user_text)
            proc.stdin.close()
        except OSError:
            pass

        final, is_error = None, False
        try:
            while True:
                line = await q.get()
                if line is None:
                    break
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = ev.get("type")
                if ev.get("session_id"):
                    self.session_id = ev["session_id"]
                if t == "assistant":
                    for b in (ev.get("message") or {}).get("content") or []:
                        if b.get("type") == "tool_use":
                            name = b.get("name", "")
                            if name.startswith("mcp__meetingroom__"):
                                name = name.split("__")[-1]
                            a.trace("tool_call", _pretty_input(b.get("input")), tool=name)
                            await a.set_status("working", f"{name}: {_brief(b.get('input'))}")
                        elif b.get("type") == "thinking" and str(b.get("thinking", "")).strip():
                            a.trace("thought", b["thinking"])
                        elif b.get("type") == "text" and b.get("text", "").strip():
                            a.trace("thought", b["text"])
                            await a.set_status("thinking", b["text"].strip()[:200])
                elif t == "user":
                    for b in (ev.get("message") or {}).get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            c = b.get("content")
                            if isinstance(c, list):
                                c = "\n".join(x.get("text", "") if x.get("type") == "text" else f"[{x.get('type')}]"
                                              for x in c if isinstance(x, dict))
                            a.trace("tool_result", str(c or ""), error=bool(b.get("is_error")))
                    await a.set_status("thinking", "Reviewing tool results…")
                elif t == "rate_limit_event":
                    info = ev.get("rate_limit_info") or {}
                    await a.room.set_quota(info)
                    if info.get("status") == "rejected":
                        raise TokenLimitReached("Plan usage limit reached; retry after the quota resets.")
                elif t == "result":
                    final = ev.get("result") or "\n".join(str(e) for e in ev.get("errors") or []) or None or "\n".join(str(e) for e in ev.get("errors") or []) or None
                    is_error = bool(ev.get("is_error")) or ev.get("subtype", "success") != "success"
                    self._record_usage(ev)
            await asyncio.to_thread(proc.wait)
        except (asyncio.CancelledError, TokenLimitReached):
            if proc.poll() is None:
                proc.kill()
            raise
        err = "".join(stderr_tail).strip()
        if final is None:
            if "No conversation found" in err or ("session" in err.lower() and self.session_id and proc.returncode):
                raise _ResumeFailed()
            raise RuntimeError(f"Claude Code exited ({proc.returncode}) without a result. {err[-800:]}")
        if is_error:
            raise RuntimeError(f"Claude Code reported an error: {final or err[-800:]}")
        return final


class CodexBackend:
    """Drives your installed OpenAI Codex CLI (`codex exec --json`), logged in
    with your ChatGPT account (no API key). Each turn resumes the same thread.
    Codex runs in its `workspace-write` sandbox (writes confined to the agent
    folder + add_dirs) since `codex exec` cannot ask for approval interactively.
    share_to_screen comes from the same local MCP bridge as Claude Code."""

    def __init__(self, agent: Agent):
        self.agent = agent
        loc = agent.room.location
        if agent.remote:
            exe = agent.spec.get("remote_codex_path") or loc.bins.get("codex")
            if not exe:
                raise RuntimeError(f"Codex CLI not found on {loc.host}. Install it there and sign in once, "
                                   "or set `remote_codex_path:` for this agent in agents.yaml.")
        else:
            exe = agent.spec.get("codex_path") or shutil.which("codex") or next(
            (str(p) for p in (Path.home() / ".local/bin/codex", Path("/opt/homebrew/bin/codex"),
                              Path("/usr/local/bin/codex")) if p.is_file()), None)
        if not exe:
            raise RuntimeError("Codex CLI not found. Put its path as `codex_path:` for this agent in agents.yaml.")
        self.exe = exe if agent.remote else str(Path(exe).expanduser())
        self.thread_id: str | None = None
        self.sandbox = agent.spec.get("sandbox", "workspace-write")
        self.network = bool(agent.spec.get("network", True))   # allow network inside the workspace-write sandbox
        self.extra_dirs = [] if agent.remote else [str(Path(d).expanduser()) for d in agent.spec.get("add_dirs", [])]

    def _meeting_prompt(self) -> str:
        return cli_meeting_prompt(self.agent,
            "Show results with the meetingroom MCP tool "
            "share_to_screen (plots as PNG/SVG, interactive pages as self-contained HTML, tables as CSV/markdown). "
            "Save figures to files and never open GUI windows.")

    def _cmd(self) -> list[str]:
        a = self.agent
        loc = a.room.location
        py, bridge = (loc.bins.get("python3"), loc.bridge) if a.remote else (sys.executable, BRIDGE)
        cmd = ["exec"]
        if self.thread_id:
            cmd += ["resume", self.thread_id]
        cmd += ["--json", "--skip-git-repo-check",
                "-c", f"mcp_servers.meetingroom.command={json.dumps(py)}",
                "-c", f"mcp_servers.meetingroom.args=[{json.dumps(bridge)}]",
                "-c", 'mcp_servers.meetingroom.env_vars=["MR_URL","MR_TOKEN","MR_AGENT","MR_HOST","MR_UPLOAD"]',
                "-c", "mcp_servers.meetingroom.tool_timeout_sec=86400",
                "-c", 'mcp_servers.meetingroom.tools.share_to_screen.approval_mode="approve"',
                "-c", 'mcp_servers.meetingroom.tools.report_progress.approval_mode="approve"',
                "-c", f"sandbox_mode={json.dumps(self.sandbox)}",
                "-c", 'approval_policy="never"']
        if self.network:
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if not self.thread_id:
            cmd += ["-C", loc.path if a.remote else str(a.workdir)]
            for d in self.extra_dirs:
                cmd += ["--add-dir", d]
        if a.model:
            cmd += ["-m", a.model]
        if a.effort:
            cmd += ["-c", f"model_reasoning_effort={json.dumps(a.effort)}"]
        cmd += ["-"]
        if a.remote:
            return loc.ssh_argv(a.name, a.room.port, self.exe, cmd, "OPENAI_API_KEY")
        return [self.exe, *cmd]

    async def _read_limits(self):
        """`codex exec --json` doesn't stream plan limits, but Codex logs them in its session
        file (~/.codex/sessions/.../rollout-*-<thread>.jsonl). Read the last token_count entry."""
        if not self.thread_id:
            return
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        files = sorted((home / "sessions").glob(f"**/rollout-*{self.thread_id}.jsonl"))
        if not files:
            return
        last = None
        with open(files[-1], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            for line in f.read().decode("utf-8", "replace").splitlines():
                if '"token_count"' in line and '"rate_limits"' in line:
                    last = line
        if not last:
            return
        pl = json.loads(last).get("payload") or {}
        rl, info = pl.get("rate_limits") or {}, pl.get("info") or {}
        names = {300: "five_hour", 10080: "seven_day"}
        wins = {}
        for key in ("primary", "secondary"):
            w = rl.get(key)
            if w and w.get("used_percent") is not None:
                wins[names.get(w.get("window_minutes"), key)] = {
                    "utilization": w["used_percent"] / 100, "resetsAt": w.get("resets_at"),
                    "status": "rejected" if rl.get("rate_limit_reached_type") else "allowed"}
        await self.agent.room.set_quota({"windows": wins}, group="codex")
        tot = (info.get("last_token_usage") or {}).get("total_tokens")
        u = self.agent.usage
        self.agent.usage = {"context_tokens": int(tot or 0), "cost_usd": None,
                            "output_tokens": int((info.get("last_token_usage") or {}).get("output_tokens") or 0),
                            "turns": int(u.get("turns", 0)) + 1}

    async def turn(self, user_text: str) -> str:
        a = self.agent
        text = user_text if self.thread_id else self._meeting_prompt() + "\n\n" + user_text
        env = bridge_env(a, "OPENAI_API_KEY")  # use the ChatGPT login
        proc = await asyncio.create_subprocess_exec(
            *self._cmd(), cwd=str(a.workdir), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, limit=16 * 1024 * 1024)
        proc.stdin.write(text.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        err_task = asyncio.create_task(proc.stderr.read())
        final, error = None, None
        active_tools = set()
        try:
            async for raw in proc.stdout:
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t, item = ev.get("type"), ev.get("item") or {}
                if item.get("type") in ("command_execution", "mcp_tool_call", "file_change"):
                    if t == "item.started":
                        active_tools.add(item.get("id"))
                        activity = (f"shell: {str(item.get('command', ''))[:120]}"
                                    if item.get("type") == "command_execution"
                                    else str(item.get("tool") or "editing files"))
                        await a.set_status("working", activity)
                    elif t == "item.completed":
                        active_tools.discard(item.get("id"))
                        if not active_tools:
                            await a.set_status("thinking", "Reviewing tool results…")
                if t == "thread.started":
                    self.thread_id = ev.get("thread_id") or self.thread_id
                elif t == "item.completed" and item.get("type") == "command_execution":
                    a.trace("tool_call", str(item.get("command", "")), tool="shell")
                    a.trace("tool_result", f"[exit {item.get('exit_code')}]\n{item.get('aggregated_output', '')}", tool="shell")
                elif t == "item.completed" and item.get("type") == "mcp_tool_call":
                    a.trace("tool_call", _pretty_input(item.get("arguments")), tool=str(item.get("tool", "tool")))
                    a.trace("tool_result", _pretty_input(item.get("result") or item.get("error")), tool=str(item.get("tool", "tool")))
                elif t == "item.completed" and item.get("type") == "file_change":
                    a.trace("tool_call", "\n".join(f"{c.get('kind')}: {c.get('path')}" for c in item.get("changes") or []),
                            tool="file_change")
                elif t == "item.completed" and item.get("type") == "agent_message":
                    if final:
                        a.trace("thought", final)
                    final = item.get("text", "")
                    if not active_tools:
                        await a.set_status("thinking", str(item.get("text", "")).strip()[:200])
                elif t == "item.completed" and item.get("type") == "reasoning":
                    a.trace("thought", str(item.get("text", "")))
                    if not active_tools:
                        # Reasoning is private; retain the last public activity instead.
                        await a.set_status("thinking", None)
                elif t in ("turn.failed", "error"):
                    error = (ev.get("error") or {}).get("message") or ev.get("message") or str(ev)
            await proc.wait()
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
            raise
        err = (await err_task).decode(errors="replace").strip()
        try:
            await self._read_limits()
        except Exception:
            pass   # usage display is best-effort
        if error:
            raise RuntimeError(str(error))
        if final is None:
            raise RuntimeError(f"Codex exited ({proc.returncode}) without a reply. {error or ''} {err[-800:]}")
        return final


class _ResumeFailed(Exception):
    pass


_CLAUDE_CACHE: dict = {}


def find_claude(configured: str | None) -> str | None:
    """Locate the Claude Code executable: configured path, PATH, the usual
    install locations, and finally the user's login shell (which also resolves
    an `alias claude=...` from ~/.zshrc)."""
    def ok(p) -> str | None:
        p = os.path.expanduser(str(p).strip().strip("'\""))
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else None

    if configured:
        return ok(configured)
    if "exe" in _CLAUDE_CACHE:
        return _CLAUDE_CACHE["exe"]
    home = Path.home()
    found = shutil.which("claude")
    for c in ([] if found else [
        home / ".claude/local/claude", home / ".local/bin/claude", "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude", home / ".npm-global/bin/claude", home / ".bun/bin/claude",
        home / ".volta/bin/claude", home / "bin/claude",
    ]):
        found = ok(c)
        if found:
            break
    if not found:
        shell = os.environ.get("SHELL") or "/bin/zsh"
        try:
            out = subprocess.run([shell, "-ilc", "command -v claude"], capture_output=True,
                                 text=True, timeout=15, stdin=subprocess.DEVNULL).stdout
            for line in reversed(out.strip().splitlines()):
                m = re.match(r"\s*(?:alias\s+)?claude=(.+)$", line) or re.match(r"claude: aliased to (.+)$", line)
                cand = (m.group(1) if m else line).strip().strip("'\"").split()[0] if line.strip() else ""
                found = ok(cand) if cand else None
                if found:
                    break
        except Exception:
            pass
    _CLAUDE_CACHE["exe"] = found
    return found


def _pretty_input(inp) -> str:
    if isinstance(inp, str):
        return inp
    if isinstance(inp, dict) and set(inp) <= {"command", "description", "timeout"} and "command" in inp:
        return (f"# {inp['description']}\n" if inp.get("description") else "") + str(inp["command"])
    try:
        return json.dumps(inp, indent=1, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(inp)


def _brief(inp) -> str:
    if not isinstance(inp, dict):
        return ""
    for k in ("command", "file_path", "path", "pattern", "url", "query", "description"):
        if inp.get(k):
            return str(inp[k]).replace("\n", " ")[:140]
    return json.dumps(inp)[:140]


class MockBackend:
    """Key-free demo participant that really runs tools, so you can try the
    room (and the approval flow) before adding any API keys."""

    def __init__(self, agent: Agent):
        self.agent = agent

    async def turn(self, user_text: str) -> str:
        a = self.agent
        req = user_text.lower()
        last = [l for l in req.splitlines() if l.startswith("[") and (f"@{a.name}" in l or "@all" in l)]
        ask = (last[-1] if last else req).lower()
        await asyncio.sleep(0.6)
        if any(w in ask for w in ("plot", "chart", "figure", "histogram")):
            code = DEMO_PLOT.replace("{NAME}", a.name)
            out = await a.exec_tool("run_python", {"code": code})
            if "exit code: 0" not in out:
                return f"The plot script failed:\n```\n{out[-600:]}\n```"
            await a.exec_tool("share_to_screen", {"path": "demo_plot.png", "title": f"{a.name}: demo threshold scan"})
            return "Here it is. I fixed the noise at 9 electrons for the fit, the tail was too sparse to fit it freely."
        if any(w in ask for w in ("html", "page", "dashboard", "table")):
            await a.exec_tool("write_file", {"path": "demo_page.html", "content": DEMO_HTML.replace("{NAME}", a.name)})
            await a.exec_tool("share_to_screen", {"path": "demo_page.html", "title": f"{a.name}: summary page"})
            return "Here it is."
        return ("I'm a demo participant, so no model is connected yet. Ask me for a *plot* or a *page* "
                "to see the tool and screen flow. Add API keys to bring in real Claude and GPT agents.")


DEMO_PLOT = r'''
import math, random
random.seed(7)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    raise SystemExit("matplotlib not installed in this Python")
xs = [i * 2.0 for i in range(60)]
mu, sig = 62.0, 9.0
ys = [min(1, max(0, 0.5 * (1 + math.erf((x - mu) / (sig * 2 ** 0.5))) + random.gauss(0, 0.025))) for x in xs]
fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
ax.plot(xs, ys, "o", ms=4, color="#4c78a8", label="pixel response")
fx = [i * 0.5 for i in range(240)]
ax.plot(fx, [0.5 * (1 + math.erf((x - mu) / (sig * 2 ** 0.5))) for x in fx], color="#e45756", lw=2,
        label=f"fit: thr = {mu:.0f} e-, noise = {sig:.0f} e-")
ax.set_xlabel("injected charge (e-)"); ax.set_ylabel("hit fraction")
ax.set_title("Demo threshold scan ({NAME})"); ax.grid(alpha=.3); ax.legend(frameon=False)
fig.tight_layout(); fig.savefig("demo_plot.png")
print("saved demo_plot.png")
'''

DEMO_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:system-ui,sans-serif;margin:32px;color:#1d2330}
h1{font-size:20px;margin:0 0 4px} p{color:#5a6475;margin:0 0 20px}
table{border-collapse:collapse;min-width:420px} td,th{padding:8px 14px;border-bottom:1px solid #e3e6ec;text-align:left}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#6b7385}
td.n{text-align:right;font-variant-numeric:tabular-nums}
</style></head><body><h1>Run summary</h1><p>Generated by {NAME} (demo data)</p>
<table><tr><th>Chip</th><th>Threshold (e-)</th><th>Noise (e-)</th><th>Dead pixels</th></tr>
<tr><td>A01</td><td class=n>101.2</td><td class=n>5.8</td><td class=n>3</td></tr>
<tr><td>A02</td><td class=n>98.7</td><td class=n>6.1</td><td class=n>0</td></tr>
<tr><td>A03</td><td class=n>104.9</td><td class=n>5.5</td><td class=n>12</td></tr></table></body></html>"""
