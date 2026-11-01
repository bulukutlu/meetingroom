"""The local hub: a FastAPI app bound to 127.0.0.1 that hosts the meeting
room page, routes messages between you and the agents, handles approvals and
serves files put on the shared screen."""
from __future__ import annotations

import asyncio
import os
import signal
import base64
import json
import re
import secrets
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .agents import Agent, assign_people
from .location import Location
from .minutes import Recorder, build as build_minutes
from .stt import Transcriber
from .tts import MessageAudio, Speaker, clean_for_speech, split_sentences

STATIC = Path(__file__).parent / "static"
MENTION = re.compile(r"@([A-Za-z0-9_\-]+)")
LEADING_MENTIONS = re.compile(r"^\s*((?:@[A-Za-z0-9_\-]+[\s,:]*)+)")
MAX_HOPS = 2  # you -> agent -> handoff -> one reply back, then it stops
KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"},
    "html": {".html", ".htm"},
    "pdf": {".pdf"},
    "text": {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".yaml", ".yml", ".tex"},
}


def kind_of(p: Path) -> str:
    for k, exts in KINDS.items():
        if p.suffix.lower() in exts:
            return k
    return "file"


def permission_summary(tool: str, inp: dict) -> str:
    if tool in ("Bash", "PowerShell") and inp.get("command"):
        d = f"# {inp['description']}\n" if inp.get("description") else ""
        return d + inp["command"]
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        body = inp.get("content") or inp.get("new_string") or inp.get("new_source") or ""
        return f"{tool} {inp.get('file_path') or inp.get('notebook_path', '')}\n\n{body[:2000]}"
    if tool in ("WebFetch", "WebSearch"):
        return f"{tool} {inp.get('url') or inp.get('query', '')}"
    return f"{tool}\n" + json.dumps(inp, indent=2)[:3000]


class Room:
    def __init__(self, cfg: dict, port: int = 0, token: str = ""):
        self.cfg = cfg
        self.port = port
        self.token = token
        self.user: str = cfg.get("user_name", "You")
        self.python: str = cfg.get("python") or "python3"
        self.workspace = Path(cfg["workspace"]).expanduser().resolve()
        self.session = time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = self.workspace / "meetings" / self.session
        self.shared_dir = self.session_dir / "shared"
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.session_dir / "transcript.jsonl"
        self.recorder = Recorder(self.session_dir)
        self.messages: list[dict] = []
        self.shared: list[dict] = []
        self.files: dict[str, Path] = {}
        self.clients: set[WebSocket] = set()
        self.approvals: dict[str, dict] = {}
        self.agents: dict[str, Agent] = {}
        self.location: Location = cfg.get("location") or Location()
        self.quota: dict = {}   # plan usage windows reported by Claude Code (account-wide)
        assign_people(cfg["agents"])
        for spec in cfg["agents"]:
            a = Agent(self, spec)
            self.agents[a.name.lower()] = a
        self.alias: dict[str, str] = {}   # first name or handle (lowercase) -> handle
        for a in self.agents.values():
            self.alias[a.person.lower()] = a.name.lower()
        for a in self.agents.values():
            self.alias[a.name.lower()] = a.name.lower()
        self.stt = Transcriber(cfg.get("voice"), self.user, [n for a in self.agents.values() for n in (a.name, a.person)])
        self.tts = Speaker(cfg.get("narration"), self.workspace, cfg["agents"])
        self.msg_audio = MessageAudio(self.tts)
        self.narrate = False   # set by the page when "Read replies aloud" is on

    async def load_stt(self):
        await asyncio.to_thread(self.stt.load)
        await self.broadcast({"type": "stt", "stt": self.stt.public()})

    async def load_tts(self):
        await asyncio.to_thread(self.tts.load)
        await self.broadcast({"type": "tts", "tts": self.tts.public()})

    # ---------------- events
    async def broadcast(self, ev: dict):
        data = json.dumps(ev)   # serialize once, not once per client
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def set_quota(self, info: dict, group: str = "claude"):
        """Store the latest plan-limit info (per provider group) and push it to the page.
        `info` is a Claude Code rate_limit_info dict, or {"windows": {...}} already normalised."""
        wins = info.get("windows") or info.get("unifiedWindows") or {}
        if not wins and info.get("rateLimitType"):
            wins = {info["rateLimitType"]: info}
        keep = {k: {"utilization": w.get("utilization"), "resetsAt": w.get("resetsAt"), "status": w.get("status")}
                for k, w in wins.items() if isinstance(w, dict)}
        if not keep:
            return
        old = self.quota.get(group, {}).get("windows", {})
        self.quota[group] = {"windows": {**old, **keep}, "asof": time.time()}
        await self.broadcast({"type": "quota", "quota": self.quota})

    def snapshot(self) -> dict:
        return {
            "quota": self.quota,
            "type": "snapshot", "user": self.user, "session": self.session,
            "workspace": str(self.workspace), "location": self.location.public(), "stt": self.stt.public(), "tts": self.tts.public(),
            "agents": [a.public() for a in self.agents.values()],
            "messages": self.messages, "shared": self.shared,
            "approvals": [{k: v for k, v in ap.items() if k != "future"} for ap in self.approvals.values()],
        }

    # ---------------- messages & routing
    async def post(self, sender: str, text: str, kind: str = "msg", hop: int = 0, turn: str | None = None) -> dict:
        if sender.lower() in self.agents:
            # Agents only wake others by a deliberate handoff: the message must
            # START with @name(s). Passing mentions never trigger anyone.
            lead = LEADING_MENTIONS.match(text)
            names = {n.lower() for n in MENTION.findall(lead.group(1))} if lead else set()
        else:
            names = {n.lower() for n in MENTION.findall(text)}
            for a in self.agents.values():   # a bare name anywhere counts too ("can you check this, Alejandro?")
                for nm in (a.name, a.person):
                    if re.search(rf"(?<![\w@-]){re.escape(nm)}(?![\w-])(?!\s+code\b)", text, re.I):
                        names.add(nm.lower())
            if not names:                     # no one addressed: answering an agent's question, or the last speaker
                q = self.open_question()
                if not q and self.cfg.get("reply_to_last_speaker", True):
                    q = self.last_speaker()
                if q:
                    names = {q}
        targets = []
        names = {self.alias.get(n, n) for n in names}
        if names & {"all", "everyone"}:
            targets = [a for a in self.agents.values() if a.name.lower() != sender.lower()]
        else:
            targets = [self.agents[n] for n in names if n in self.agents and n != sender.lower()]
        m = {"id": uuid.uuid4().hex[:10], "from": sender, "text": text, "kind": kind,
             "ts": time.time(), "to": [a.name for a in targets]}
        if turn:
            m["turn"] = turn
        self.messages.append(m)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(m) + "\n")
        if kind == "msg" and self.narrate and self.tts.status == "ready" and sender.lower() in self.agents:
            self.msg_audio.start(m["id"], text, sender)   # start voicing before the page even asks
        await self.broadcast({"type": "message", "message": m})
        if kind == "msg" and hop <= MAX_HOPS:
            for a in targets:
                a.queue.put_nowait(hop)
        return m

    def last_speaker(self) -> str | None:
        """Most recent agent that posted a message (None if no agent has spoken yet)."""
        for m in reversed(self.messages):
            if m["kind"] == "msg" and m["from"].lower() in self.agents:
                return m["from"].lower()
        return None

    def open_question(self) -> str | None:
        """Agent whose message is the latest in the room and ends with a question."""
        last = next((m for m in reversed(self.messages) if m["kind"] == "msg"), None)
        if last and last["from"].lower() in self.agents and last["text"].rstrip(" *_`\"')").endswith("?"):
            return last["from"].lower()
        return None

    # ---------------- approvals
    async def request_approval(self, agent: Agent, tool: str, summary: str) -> bool:
        aid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        ap = {"id": aid, "agent": agent.name, "tool": tool, "summary": summary[:6000],
              "ts": time.time(), "future": fut}
        self.approvals[aid] = ap
        await self.broadcast({"type": "approval", "approval": {k: v for k, v in ap.items() if k != "future"}})
        try:
            return await fut
        finally:
            self.approvals.pop(aid, None)
            await self.broadcast({"type": "approval_done", "id": aid})

    def resolve_approval(self, aid: str, decision: str):
        ap = self.approvals.get(aid)
        if not ap or ap["future"].done():
            return
        if decision == "always":
            a = self.agents.get(ap["agent"].lower())
            if a:
                a.approval = "auto"
        ap["future"].set_result(decision in ("yes", "always"))

    # ---------------- shared screen
    async def share(self, agent: Agent, path: Path, title: str, source: str | None = None) -> str:
        fid = uuid.uuid4().hex[:12]
        name = path.name.split("_", 1)[1] if source else path.name
        dest = self.shared_dir / f"{fid}_{name}"
        shutil.copy2(path, dest)
        self.files[fid] = dest
        item = {"id": fid, "agent": agent.name, "title": title, "name": name,
                "kind": kind_of(path), "ts": time.time(), "source": source or str(path)}
        self.shared.append(item)
        self.recorder.write(agent.name, "share", source or str(path), turn=getattr(agent, "turn_id", None), title=title,
                           copy=f"shared/{dest.name}")
        await self.broadcast({"type": "shared", "item": item})
        return f"'{name}' is now on the shared screen."


def _minutes_summary(room) -> dict:
    """Build minutes now and collect them (current + earlier sessions) for the goodbye page."""
    try:
        build_minutes(room.session_dir)
    except Exception:
        pass
    out = []
    root = room.session_dir.parent
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), reverse=True) if root.exists() else []
    for d in dirs:
        mp = d / "minutes.md"
        if not mp.exists():
            continue
        try:
            txt = mp.read_text(encoding="utf-8", errors="replace")[:80000]
        except OSError:
            continue
        out.append({"session": d.name, "path": str(mp), "text": txt, "current": d == room.session_dir})
    return {"current": str(room.session_dir / "minutes.md"), "sessions": out}


def create_app(cfg: dict, port: int, token: str) -> FastAPI:
    room_holder: dict = {}
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    @asynccontextmanager
    async def lifespan(app):
        room = Room(cfg, port, token)
        room_holder["room"] = room
        tasks = [asyncio.create_task(a.run_forever()) for a in room.agents.values()]
        tasks.append(asyncio.create_task(room.load_stt()))
        tasks.append(asyncio.create_task(room.load_tts()))
        yield
        for t in tasks:
            t.cancel()
        try:
            room.location.close()
        except Exception:
            pass
        try:
            mp = build_minutes(room.session_dir)
            print(f"Meeting minutes: {mp}" if mp else "Empty meeting, no minutes written.")
        except Exception as e:
            print(f"could not write minutes: {e}")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        # Blocks DNS-rebinding: only requests addressed to localhost are served.
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    def check_token(t: str | None):
        if not t or not secrets.compare_digest(t, token):
            raise HTTPException(403, "bad token")

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/files/{fid}")
    async def files(fid: str, t: str | None = None):
        check_token(t)
        p = room_holder["room"].files.get(fid)
        if not p or not p.exists():
            raise HTTPException(404)
        headers = {}
        if p.suffix.lower() in (".html", ".htm", ".svg"):
            # Agent-made pages run sandboxed: no access to this app's origin.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-forms"
        return FileResponse(p, headers=headers)

    @app.post("/stt")
    async def stt(request: Request, t: str | None = None):
        # Local transcription: 16 kHz mono float32 PCM from the page, never sent anywhere.
        check_token(t)
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(403, "bad origin")
        body = await request.body()
        if len(body) > 16000 * 4 * 180 or len(body) % 4:
            raise HTTPException(413, "audio too long")
        import numpy as np
        audio = np.frombuffer(body, dtype="<f4").astype(np.float32)
        room: Room = room_holder["room"]
        prev = unquote(request.headers.get("x-prompt", ""))[-300:]
        try:
            text = await asyncio.to_thread(room.stt.transcribe, audio, prev)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        return {"text": text}

    @app.post("/tts/plan")
    async def tts_plan(request: Request, t: str | None = None):
        check_token(t)
        body = await request.json()
        return {"parts": split_sentences(clean_for_speech(str(body.get("text", ""))[:4000]))}

    @app.post("/tts")
    async def tts(request: Request, t: str | None = None):
        # Local narration: returns a WAV of one sentence in the agent's voice.
        check_token(t)
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(403, "bad origin")
        body = await request.json()
        room: Room = room_holder["room"]
        try:
            wav = await asyncio.to_thread(room.tts.synth_wav, str(body.get("text", "")), str(body.get("agent", "")))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        return Response(wav, media_type="audio/wav")

    @app.post("/tts/msg")
    async def tts_msg(request: Request, t: str | None = None):
        check_token(t)
        room: Room = room_holder["room"]
        mid = str((await request.json()).get("mid", ""))
        m = next((x for x in reversed(room.messages) if x["id"] == mid), None)
        if not m or room.tts.status != "ready":
            return {"parts": []}
        return {"parts": room.msg_audio.start(mid, m["text"], m["from"])}

    @app.get("/tts/msg/{mid}/{i}")
    async def tts_msg_part(mid: str, i: int, t: str | None = None):
        check_token(t)
        room: Room = room_holder["room"]
        wav = await asyncio.to_thread(room.msg_audio.get, mid, i)
        if not wav:
            raise HTTPException(404)
        return Response(wav, media_type="audio/wav")

    @app.get("/tts/ack/{agent}/{i}")
    async def tts_ack(agent: str, i: int, t: str | None = None):
        check_token(t)
        clips = room_holder["room"].tts.acks.get(agent.lower()) or []
        if not clips:
            raise HTTPException(404)
        return Response(clips[i % len(clips)], media_type="audio/wav")

    @app.get("/tts/perm/{agent}/{i}")
    async def tts_perm(agent: str, i: int, t: str | None = None):
        check_token(t)
        clips = room_holder["room"].tts.perms.get(agent.lower()) or []
        if not clips:
            raise HTTPException(404)
        return Response(clips[i % len(clips)], media_type="audio/wav")

    # ---- endpoints used by the MCP bridge inside Claude Code agents
    async def internal_body(request: Request) -> tuple[Room, Agent, dict]:
        check_token(request.headers.get("x-mr-token"))
        body = await request.json()
        room: Room = room_holder["room"]
        a = room.agents.get(str(body.get("agent", "")).lower())
        if not a:
            raise HTTPException(404, "unknown agent")
        return room, a, body

    @app.post("/internal/permission")
    async def internal_permission(request: Request):
        room, a, body = await internal_body(request)
        tool, inp = str(body.get("tool_name") or "?"), body.get("input") or {}
        if a.approval == "auto":
            return {"allow": True}
        await a.set_status("waiting", f"waiting for approval: {tool}")
        ok = await room.request_approval(a, tool, permission_summary(tool, inp))
        await a.set_status("working", f"{tool} approved" if ok else f"{tool} denied")
        return {"allow": ok}

    @app.post("/internal/share")
    async def internal_share(request: Request):
        room, a, body = await internal_body(request)
        if body.get("content_b64"):         # remote (SSH) agent uploaded the file itself
            name = Path(str(body.get("path") or "file")).name or "file"
            up = room.session_dir / "uploads" / f"{uuid.uuid4().hex[:8]}_{name}"
            up.parent.mkdir(exist_ok=True)
            try:
                up.write_bytes(base64.b64decode(body["content_b64"]))
            except Exception as e:
                return {"text": f"error: bad upload: {e}"}
            src = f"{room.location.host}:{body.get('path')}" if room.location.remote else str(body.get("path") or name)
            return {"text": await room.share(a, up, body.get("title") or name, source=src)}
        p = Path(str(body.get("path", ""))).expanduser()
        if not p.is_absolute():
            p = a.workdir / p
        if not p.is_file():
            return {"text": f"error: {p} does not exist"}
        return {"text": await room.share(a, p.resolve(), body.get("title") or p.name)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if (websocket.headers.get("host") not in allowed_hosts
                or websocket.headers.get("origin") not in allowed_origins
                or not secrets.compare_digest(websocket.query_params.get("t", ""), token)):
            await websocket.accept()
            await websocket.close(code=4403)  # tells the page "access denied"
            return
        room: Room = room_holder["room"]
        await websocket.accept()
        room.clients.add(websocket)
        await websocket.send_text(json.dumps(room.snapshot()))
        try:
            while True:
                ev = json.loads(await websocket.receive_text())
                typ = ev.get("type")
                if typ == "say" and ev.get("text", "").strip():
                    await room.post(room.user, ev["text"].strip())
                elif typ == "approve":
                    room.resolve_approval(ev.get("id", ""), ev.get("decision", "no"))
                elif typ == "stop":
                    a = room.agents.get(str(ev.get("agent", "")).lower())
                    if a:
                        a.stop()
                elif typ == "stop_all":
                    for a in room.agents.values():
                        a.stop()
                elif typ == "quit":
                    for a in room.agents.values():
                        a.stop()
                    await room.broadcast({"type": "bye", "minutes": _minutes_summary(room)})
                    loop = asyncio.get_running_loop()
                    loop.call_later(0.8, os.kill, os.getpid(), signal.SIGINT)   # graceful uvicorn shutdown -> minutes, ssh cleanup
                elif typ == "prefs":
                    room.narrate = bool(ev.get("narrate"))
                elif typ == "set_approval":
                    a = room.agents.get(str(ev.get("agent", "")).lower())
                    if a and ev.get("mode") in ("ask", "auto"):
                        a.approval = ev["mode"]
                        await room.broadcast({"type": "agent", "agent": a.public()})
                elif typ == "set_effort":
                    a = room.agents.get(str(ev.get("agent", "")).lower())
                    lvl = str(ev.get("effort") or "")
                    if a and (lvl == "" or lvl in a.public()["efforts"]):
                        a.effort = lvl
                        await room.broadcast({"type": "agent", "agent": a.public()})
        except WebSocketDisconnect:
            pass
        finally:
            room.clients.discard(websocket)

    return app
