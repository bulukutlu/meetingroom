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

from . import annotate, saved
from .agents import Agent, assign_people
from .location import Location
from .minutes import Recorder, build as build_minutes
from .stt import Transcriber
from .tts import MessageAudio, Speaker, clean_for_speech, split_sentences

STATIC = Path(__file__).parent / "static"
MENTION = re.compile(r"@([A-Za-z0-9_\-]+)")
LEADING_MENTIONS = re.compile(r"^\s*((?:@[A-Za-z0-9_\-]+[\s,:]*)+)")
MAX_HOPS = 2  # you -> agent -> handoff -> one reply back, then it stops
# Chains involving a supervisor agent (`supervisor: true` in agents.yaml) may run
# 3 full round trips: user -> S -> W -> S -> W -> S -> W -> S, then it stops.
MAX_HOPS_SUPERVISED = 6
KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"},
    "html": {".html", ".htm"},
    "pdf": {".pdf"},
    "text": {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".yaml", ".yml", ".tex"},
}


# Injected into shared HTML pages only while you are marking them (see /files).
MARK_HELPER = """<script>(()=>{const P=window.parent;if(P===window)return;
const send=o=>P.postMessage(Object.assign({mr:1},o),"*");
document.addEventListener("mouseup",()=>setTimeout(()=>{const s=String(getSelection()||"").trim();
 if(s)send({kind:"selection",text:s.slice(0,4000),scroll:[scrollX,scrollY]});},0));
addEventListener("message",e=>{const d=e.data||{};if(!d.mrBox)return;const[x0,y0,x1,y1]=d.mrBox,W=innerWidth,H=innerHeight;
 const R={l:x0*W,t:y0*H,r:x1*W,b:y1*H},out=[],seen=new Set();
 const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
 while((n=w.nextNode())){const t=n.textContent.trim();if(!t)continue;const r=document.createRange();r.selectNodeContents(n);
  const b=r.getBoundingClientRect();if(b.right<R.l||b.left>R.r||b.bottom<R.t||b.top>R.b)continue;
  if(!seen.has(n.parentElement)){seen.add(n.parentElement);out.push(t);}}
 send({kind:"box",id:d.id,text:out.join(" ").slice(0,4000),scroll:[scrollX,scrollY]});});})();</script>"""


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
    def __init__(self, cfg: dict, port: int = 0, token: str = "", rid: str = "", title: str = "", session: str = ""):
        self.cfg = cfg
        self.port = port
        self.token = token
        self.rid = rid or uuid.uuid4().hex[:6]
        self.base = f"/r/{self.rid}"          # every room lives under its own path on the one hub
        self.title = title
        self.created = time.time()
        self.tasks: list[asyncio.Task] = []
        self.user: str = cfg.get("user_name", "You")
        self.python: str = cfg.get("python") or "python3"
        self.workspace = Path(cfg["workspace"]).expanduser().resolve()
        self.session = session or time.strftime("%Y%m%d-%H%M%S")
        if not session and (self.workspace / "meetings" / self.session).exists():   # two rooms opened in the same second
            self.session += f"-{self.rid}"
        self.session_dir = self.workspace / "meetings" / self.session
        self.shared_dir = self.session_dir / "shared"
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.session_dir / "transcript.jsonl"
        self.recorder = Recorder(self.session_dir)
        self.messages: list[dict] = []
        self.shared: list[dict] = []
        self.files: dict[str, Path] = {}
        self.anchors: dict[str, dict] = {}   # marks you made on the shared screen
        self.attachments: dict[str, dict] = {}   # files you attached to messages (id -> info)
        self.marks_dir = self.session_dir / "marks"
        self.clients: set[WebSocket] = set()
        self.approvals: dict[str, dict] = {}
        self.agents: dict[str, Agent] = {}
        self.location: Location = cfg.get("location") or Location()
        self.location.url_base = self.base
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
            "type": "snapshot", "user": self.user, "session": self.session, "room": self.rid, "title": self.title,
            "workspace": str(self.workspace), "location": self.location.public(), "stt": self.stt.public(), "tts": self.tts.public(),
            "agents": [a.public() for a in self.agents.values()],
            "messages": self.messages, "shared": self.shared,
            "approvals": [{k: v for k, v in ap.items() if k != "future"} for ap in self.approvals.values()],
        }

    def lobby_info(self) -> dict:
        """What the corridor shows on this room's door."""
        return {"id": self.rid, "title": self.title, "label": self.location.label(), "kind": self.location.kind,
                "created": self.created, "session": self.session, "messages": sum(m["kind"] == "msg" for m in self.messages),
                "approvals": len(self.approvals),
                "agents": [{k: a.public().get(k) for k in ("name", "person", "color", "status")} for a in self.agents.values()]}

    def start(self):
        self.tasks = [asyncio.create_task(a.run_forever()) for a in self.agents.values()]
        self.tasks += [asyncio.create_task(self.load_stt()), asyncio.create_task(self.load_tts())]

    async def shutdown(self, next_page: str | None = None, save: bool = True):
        """Stop the agents, write the minutes, say goodbye to open pages, drop the SSH session."""
        self.msg_audio.close()
        for a in self.agents.values():
            a.stop()
        for t in self.tasks:
            t.cancel()
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=5)
        saved.checkpoint(self, "saved" if save else "discarded")
        minutes = await asyncio.to_thread(_minutes_summary, self)
        if next_page is not None:
            await self.broadcast({"type": "bye", "minutes": minutes, "next": next_page})
        for ws in list(self.clients):
            try:
                await ws.close(code=1000)
            except Exception:
                pass
        try:
            await asyncio.to_thread(self.location.close)
        except Exception:
            pass
        cur = self.session_dir / "minutes.md"
        print(f"  Room '{self.title}' closed. " + (f"Minutes: {cur}" if cur.exists() else "Empty meeting, no minutes written."), flush=True)

    # ---------------- messages & routing
    async def post(self, sender: str, text: str, kind: str = "msg", hop: int = 0, turn: str | None = None,
                   anchors: list[dict] | None = None, attachments: list[dict] | None = None) -> dict:
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
            if not names and anchors:         # a comment on the screen goes to whoever put that thing there
                names = {a["owner"].lower() for a in anchors}
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
        if anchors:
            m["anchors"] = anchors
        if attachments:
            m["attachments"] = attachments
        self.messages.append(m)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(m) + "\n")
        saved.checkpoint(self)
        if kind == "msg" and self.narrate and self.tts.status == "ready" and sender.lower() in self.agents:
            self.msg_audio.start(m["id"], text, sender)   # start voicing before the page even asks
        await self.broadcast({"type": "message", "message": m})
        limit = MAX_HOPS
        if any(getattr(self.agents.get(n.lower()), "supervisor", False) for n in [sender, *m["to"]]):
            limit = MAX_HOPS_SUPERVISED
        if kind == "msg" and hop <= limit:
            for a in targets:
                if sender.lower() in self.agents:
                    a.requesters.add(sender.lower())   # who handed this work over; they must be answered by name
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
        saved.checkpoint(self)
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


def room_app(room: Room, hub) -> FastAPI:
    """The endpoints of one room; the hub mounts it at room.base (/r/<id>)."""
    room_holder = {"room": room}
    token, allowed_hosts, allowed_origins = hub.token, hub.allowed_hosts, hub.allowed_origins
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    check_token = hub.check_token

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/files/{fid}")
    async def files(fid: str, t: str | None = None, mark: int = 0):
        check_token(t)
        p = room_holder["room"].files.get(fid)
        if not p or not p.exists():
            raise HTTPException(404)
        headers = {}
        if p.suffix.lower() in (".html", ".htm", ".svg"):
            # Agent-made pages run sandboxed: no access to this app's origin.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-forms"
        if mark and p.suffix.lower() in (".html", ".htm"):
            # Marking mode: a tiny helper reports text selections / text under a box to
            # the room page via postMessage (the page can't reach into the sandbox).
            html = p.read_text(encoding="utf-8", errors="replace")
            return HTMLResponse(html + MARK_HELPER, headers=headers)
        return FileResponse(p, headers=headers)

    @app.get("/files/{fid}/pdf")
    async def pdf_meta(fid: str, t: str | None = None):
        check_token(t)
        p = room_holder["room"].files.get(fid)
        if not p or not p.exists() or p.suffix.lower() != ".pdf":
            raise HTTPException(404)
        return await asyncio.to_thread(annotate.pdf_info, p)

    @app.get("/files/{fid}/page/{n}")
    async def pdf_page(fid: str, n: int, t: str | None = None):
        check_token(t)
        room: Room = room_holder["room"]
        p = room.files.get(fid)
        if not p or not p.exists() or p.suffix.lower() != ".pdf" or not annotate.pdf_available():
            raise HTTPException(404)
        try:
            png = await asyncio.to_thread(annotate.pdf_page_png, p, n, room.session_dir / "pages")
        except Exception:
            raise HTTPException(404)
        return FileResponse(png)

    @app.post("/annotate")
    async def make_mark(request: Request, t: str | None = None):
        check_token(t)
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(403, "bad origin")
        room: Room = room_holder["room"]
        body = await request.json()
        item = next((s for s in room.shared if s["id"] == body.get("item")), None)
        p = room.files.get(str(body.get("item")))
        if not item or not p:
            raise HTTPException(404)
        try:
            a = await asyncio.to_thread(annotate.build_anchor, item, p, body, room.marks_dir)
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)
        room.anchors[a["id"]] = a
        saved.checkpoint(room)
        return a

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

    @app.post("/attach")
    async def attach(request: Request, t: str | None = None):
        # A file the user attaches to a message: saved in the session, then handed to the agents by path.
        check_token(t)
        if request.headers.get("origin") not in allowed_origins:
            raise HTTPException(403, "bad origin")
        body = await request.body()
        if len(body) > 50 * 1024 * 1024:
            raise HTTPException(413, "file too large (50 MB max)")
        room: Room = room_holder["room"]
        name = re.sub(r"[^\w.\- ]", "_", Path(unquote(request.headers.get("x-filename", "file"))).name)[:120] or "file"
        aid = uuid.uuid4().hex[:8]
        dest = room.session_dir / "attachments"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{aid}_{name}"
        path.write_bytes(body)
        room.attachments[aid] = {"id": aid, "name": name, "size": len(body), "path": str(path),
                                 "image": name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))}
        saved.checkpoint(room)
        return room.attachments[aid]

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
                if typ == "say" and (ev.get("text", "").strip() or ev.get("anchors") or ev.get("attachments")):
                    anchors = [room.anchors[i] for i in ev.get("anchors") or [] if i in room.anchors]
                    atts = [room.attachments[i] for i in ev.get("attachments") or [] if i in room.attachments]
                    text = ev.get("text", "").strip() or ("Look at this." if anchors or atts else "")
                    if text:
                        await room.post(room.user, text, anchors=anchors or None, attachments=atts or None)
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
                    asyncio.create_task(hub.quit(save=ev.get("save", True) is not False))
                elif typ == "close_room":
                    asyncio.create_task(hub.close_room(room.rid, next_page="lobby", save=ev.get("save", True) is not False))
                elif typ == "prefs":
                    room.narrate = bool(ev.get("narrate"))
                elif typ == "set_approval":
                    a = room.agents.get(str(ev.get("agent", "")).lower())
                    if a and ev.get("mode") in ("ask", "auto"):
                        a.approval = ev["mode"]
                        saved.checkpoint(room)
                        await room.broadcast({"type": "agent", "agent": a.public()})
                elif typ == "set_effort":
                    a = room.agents.get(str(ev.get("agent", "")).lower())
                    lvl = str(ev.get("effort") or "")
                    if a and (lvl == "" or lvl in a.public()["efforts"]):
                        a.effort = lvl
                        saved.checkpoint(room)
                        await room.broadcast({"type": "agent", "agent": a.public()})
        except WebSocketDisconnect:
            pass
        finally:
            room.clients.discard(websocket)

    return app


class Hub:
    """One local server, many rooms. The corridor (lobby) at / lists them as doors and
    sets up new ones; each room runs independently under /r/<id>/ until it is closed."""

    def __init__(self, cfg: dict, port: int, token: str):
        self.cfg, self.port, self.token = cfg, port, token
        self.rooms: dict[str, Room] = {}
        self.mounts: dict[str, object] = {}
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.app: FastAPI | None = None
        self._quitting = False
        self._restoring: set[str] = set()
        self._closing: set[str] = set()

    def check_token(self, t: str | None):
        if not t or not secrets.compare_digest(t, self.token):
            raise HTTPException(403, "bad token")

    def room_url(self, rid: str) -> str:
        return f"/r/{rid}/?t={self.token}"

    async def open_room(self, names: list[str], loc: Location, title: str = "", rid: str = "",
                        session: str = "", state: dict | None = None) -> Room:
        """Seat the chosen agents in a new room at `loc` (connecting over SSH first if needed)."""
        from .agents import expand_agents
        rid = rid or uuid.uuid4().hex[:6]
        if loc.remote:
            print(f"  Connecting to {loc.host} ...", flush=True)
            await asyncio.to_thread(loc.connect, self.port, self.token, rid)
        n = len(self.rooms) + 1
        title = (title or "").strip()[:60] or (Path(loc.path).name if loc.path else "") or f"Room {n}"
        specs = ([{k: v for k, v in a["spec"].items() if k in saved.SPEC_KEYS}
                  for a in state["agents"]] if state else expand_agents(self.cfg["agents"], names))
        cfg = {**self.cfg, "agents": specs, "location": loc}
        try:
            room = Room(cfg, self.port, self.token, rid=rid, title=title, session=session)
            if state:
                saved.restore(room, state)
            saved.checkpoint(room)
        except Exception:
            loc.close()
            raise
        self.rooms[rid] = room
        from starlette.routing import Mount
        m = Mount(room.base, app=room_app(room, self))
        self.app.router.routes.insert(0, m)   # ahead of the hub's /r/{rid}/ fallback
        self.mounts[rid] = m
        room.start()
        print(f"\n  Room '{title}' open: {', '.join('@' + x['name'] for x in cfg['agents'])}"
              + (f"  ·  {loc.label()}" if loc.label() else "") + ("  (over SSH)" if loc.remote else ""), flush=True)
        return room

    async def close_room(self, rid: str, next_page: str | None = None, save: bool = True):
        room = self.rooms.get(rid)
        if not room or rid in self._closing:
            return
        self._closing.add(rid)
        try:
            await room.shutdown(next_page, save=save)
            self.rooms.pop(rid, None)
            m = self.mounts.pop(rid, None)
            if m in self.app.router.routes:
                self.app.router.routes.remove(m)
        except Exception as e:
            await room.broadcast({"type": "close_error", "error": f"Could not save and close the meeting: {e}. Free disk space and try again."})
            raise
        finally:
            self._closing.discard(rid)

    async def quit(self, save: bool = True):
        if self._quitting:
            return
        self._quitting = True
        results = await asyncio.gather(*(self.close_room(rid, next_page="end", save=save) for rid in list(self.rooms)), return_exceptions=True)
        if any(isinstance(r, BaseException) for r in results) or self.rooms:
            self._quitting = False
            return
        asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGINT)   # graceful uvicorn shutdown


def create_hub(cfg: dict, port: int, token: str, initial: dict | None = None) -> FastAPI:
    """The app uvicorn serves. `initial` = {"names", "location", "rid"} opens a room right away
    (command-line --agents/--all); otherwise you start in the corridor."""
    from . import picker
    hub = Hub(cfg, port, token)

    @asynccontextmanager
    async def lifespan(app):
        if initial:
            try:
                await hub.open_room(initial["names"], initial["location"], rid=initial.get("rid", ""))
            except Exception as e:   # e.g. the SSH tunnel failed: keep the app up, the corridor still works
                print(f"  could not open the first room: {e}", flush=True)
        yield
        await asyncio.gather(*(hub.close_room(rid) for rid in list(hub.rooms)), return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    hub.app = app
    app.state.hub = hub

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        # Blocks DNS-rebinding: only requests addressed to localhost are served.
        if request.headers.get("host") not in hub.allowed_hosts:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def lobby(t: str | None = None):
        hub.check_token(t)
        return HTMLResponse(picker.lobby_page(cfg["agents"], token))

    async def lobby_body(request: Request, t: str | None):
        hub.check_token(t)
        if request.headers.get("origin") not in hub.allowed_origins:
            raise HTTPException(403, "bad origin")
        try:
            body = await request.json()
        except Exception:
            body = None
        return body if isinstance(body, dict) else {}

    @app.get("/r/{rid}/{rest:path}")
    async def gone(rid: str, rest: str = ""):
        # A room that was closed (or never opened): send the page back to the corridor.
        return HTMLResponse("<!doctype html><title>Room closed</title><body style='background:#0e0907;color:#efe6d6;"
                            "font:15px system-ui;text-align:center;padding-top:30vh'>This room is closed. Back to the corridor…"
                            "<script>const t=new URLSearchParams(location.search).get('t')||sessionStorage.getItem('mr_t')||'';"
                            "setTimeout(()=>location.replace('/?t='+encodeURIComponent(t)),900)</script>", status_code=404)

    @app.get("/api/rooms")
    async def rooms(t: str | None = None):
        hub.check_token(t)
        return {"rooms": [r.lobby_info() for r in hub.rooms.values()]}

    @app.get("/api/saved")
    async def saved_rooms(t: str | None = None):
        hub.check_token(t)
        root = Path(cfg["workspace"]).expanduser().resolve() / "meetings"
        return {"rooms": saved.list_saved(root, {r.session for r in hub.rooms.values()})}

    @app.post("/api/restore")
    async def restore_room(request: Request, t: str | None = None):
        b = await lobby_body(request, t)
        session = str(b.get("session") or "")
        existing = next((r for r in hub.rooms.values() if r.session == session), None)
        if existing:
            return {"url": hub.room_url(existing.rid)}
        if session in hub._restoring:
            return JSONResponse({"error": "This meeting is already being reopened. Try again shortly."}, status_code=409)
        hub._restoring.add(session)
        try:
            root = Path(cfg["workspace"]).expanduser().resolve() / "meetings"
            state = saved.read(root, session)
            loc = Location.from_dict(state["location"])
            if err := await asyncio.to_thread(loc.validate):
                raise ValueError(err)
            room = await hub.open_room([], loc, title=state["title"], session=session, state=state)
            return {"url": hub.room_url(room.rid)}
        except Exception as e:
            return JSONResponse({"error": f"Could not reopen meeting: {e}"}, status_code=400)
        finally:
            hub._restoring.discard(session)

    @app.post("/ls")
    async def ls(request: Request, t: str | None = None):
        from .location import list_dirs
        b = await lobby_body(request, t)
        return await asyncio.to_thread(list_dirs, str(b.get("path") or "~"), str(b.get("host") or "") or None)

    @app.post("/probe")
    async def probe_(request: Request, t: str | None = None):
        from .location import probe
        b = await lobby_body(request, t)
        return await asyncio.to_thread(probe, str(b.get("host") or ""), str(b.get("path") or "~"))

    @app.post("/select")
    async def select(request: Request, t: str | None = None):
        b = await lobby_body(request, t)
        valid = {a["name"] for a in cfg["agents"]}
        names = [n for n in b.get("agents") or [] if n in valid][:12]
        if not names:
            return JSONResponse({"error": "choose at least one participant"}, status_code=400)
        loc = Location.from_dict(b.get("location"))
        if err := await asyncio.to_thread(loc.validate):
            return JSONResponse({"error": err}, status_code=400)
        try:
            room = await hub.open_room(names, loc, title=str(b.get("name") or ""))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"location": {"kind": loc.kind, "path": loc.path, "host": loc.host}, "room": room.rid,
                "url": hub.room_url(room.rid)}

    @app.post("/api/close/{rid}")
    async def close(rid: str, request: Request, t: str | None = None):
        b = await lobby_body(request, t)
        if rid not in hub.rooms:
            raise HTTPException(404)
        await hub.close_room(rid, next_page="lobby", save=b.get("save", True) is not False)
        return {"ok": True}

    return app
