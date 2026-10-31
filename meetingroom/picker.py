"""Start-up participant picker: a tiny local page (multi-select drop-down) that
asks which of the configured agents should join this meeting. It runs on the
same port as the room and shuts down before the room starts."""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agents import agent_face

STATIC = Path(__file__).parent / "static"


def _char_source() -> str:
    """The room's own buildChar() (same body), lifted from room3d.js so the picker never drifts from it."""
    src = (STATIC / "room3d.js").read_text()
    a, b = src.index("const B = {"), src.index("// ---------------------------------------------------------------- homography")
    return src[a:b].replace('new URL("./faces/" + face.file, import.meta.url).href', '"/faces/" + face.file + Q')
ASSETS = {"/vendor/three.min.js": "text/javascript", "/faces/faces.json": "application/json"}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Meeting room - participants</title>
<style>
 :root{--bg:#120d09;--panel:#1b1510;--panel2:#241c15;--line:#352a1f;--line2:#46382a;--text:#efe6d6;--muted:#a8977f;--dim:#76664f;--amber:#f0b44a;--accent:#9fe38f}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--text);
  background:radial-gradient(ellipse at 50% 28%,#3a2614 0,#1c130c 48%,#0e0907 100%);display:flex;flex-direction:column;align-items:center;padding:7vh 20px 40px}
 body:before{content:"";position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,#0000 0 3px,#00000018 3px 4px)}
 h1{font:700 13px ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;margin:0 0 6px;color:var(--amber)}
 h2{font-size:26px;font-weight:600;margin:0 0 6px} p.sub{color:var(--muted);margin:0 0 30px}
 .grid{display:flex;flex-wrap:wrap;gap:22px;justify-content:center;max-width:980px}
 .card{position:relative;width:200px;padding:12px 12px 14px;background:linear-gradient(#241c15,#1b1510);border:2px solid var(--line2);border-radius:10px;
  cursor:pointer;user-select:none;transition:transform .15s,border-color .15s,opacity .2s,filter .2s;box-shadow:0 8px 22px #0008}
 .card:hover{transform:translateY(-4px)}
 .card .win{height:190px;border-radius:6px;overflow:hidden;background:radial-gradient(circle at 50% 30%,#4a3320,#1a120c 75%);border:1px solid var(--line)}
 .card canvas{width:100%;height:100%;display:block;image-rendering:pixelated}
 .card:not(.on){opacity:.5;filter:grayscale(.85)}
 .card.on{border-color:var(--c);box-shadow:0 0 0 1px var(--c),0 0 26px -6px var(--c),0 8px 22px #0008}
 .name{margin-top:10px;font-weight:700;display:flex;align-items:center;gap:8px}
 .name i{width:9px;height:9px;background:var(--c);display:inline-block}
 .role{color:var(--muted);font-size:12px;margin-top:2px;min-height:34px}
 .chair{position:absolute;top:8px;right:8px;font:700 10px ui-monospace,Menlo,monospace;letter-spacing:.08em;padding:3px 7px;border-radius:4px;background:#000a;color:var(--dim)}
 .on .chair{background:var(--c);color:#1a120c}
 .bar{margin-top:30px;display:flex;gap:14px;align-items:center}
 .go{padding:12px 30px;background:var(--amber);color:#1a120c;border:0;border-radius:8px;font:700 15px system-ui;cursor:pointer;box-shadow:0 4px 0 #8a5f1c}
 .go:active{transform:translateY(3px);box-shadow:0 1px 0 #8a5f1c}.go:disabled{opacity:.4;cursor:default}
 .link{color:var(--muted);font-size:13px;cursor:pointer;padding:6px 8px}.link:hover{color:var(--text)}
</style></head><body>
<h1>&#9679; Meeting room</h1><h2>Who joins this meeting?</h2><p class="sub">Click to pull up a chair. Empty chairs stay dark.</p>
<div class="grid" id="grid"></div>
<div class="bar"><span class="link" id="all">Select all / none</span><button class="go" id="go">Start meeting</button></div>
<script type="module">
const AGENTS=__AGENTS__, T=__TOKEN__, KEY='mr-agents', Q='?t='+encodeURIComponent(T);
const THREE=await import('/vendor/three.min.js'+Q);
const FACES=await fetch('/faces/faces.json'+Q).then(r=>r.json()).catch(()=>[]);
let sel=new Set((JSON.parse(localStorage.getItem(KEY)||'null')||AGENTS.map(a=>a.name)).filter(n=>AGENTS.some(a=>a.name===n)));
if(!sel.size)AGENTS.forEach(a=>sel.add(a.name));
const $=id=>document.getElementById(id), grid=$('grid'), busts=[];
const texLoader=new THREE.TextureLoader();
__CHAR__
function bust(a,canvas){
 const f=FACES[(a.face||1)-1];
 const r=new THREE.WebGLRenderer({canvas,antialias:false,alpha:true});r.setPixelRatio(.5);
 const sc=new THREE.Scene(), cam=new THREE.PerspectiveCamera(24,1,.1,20);
 sc.add(new THREE.HemisphereLight(0xfff0d8,0x4a3320,1.1));const d=new THREE.DirectionalLight(0xffd9a0,.9);d.position.set(2,3,3);sc.add(d);
 const rig=buildChar(parseInt(a.color.slice(1),16),f,0x2f3440);rig.root.rotation.y=0;sc.add(rig.root);
 rig.armL.rotation.z=.06;rig.armR.rotation.z=-.06;
 cam.position.set(0,1.62,2.1);cam.lookAt(0,1.4,0);
 const ph=Math.random()*6;
 busts.push(t=>{const on=sel.has(a.name);rig.root.rotation.y=Math.sin(t*.7+ph)*(on?.5:.2);
  rig.head.rotation.x=Math.sin(t*1.1+ph)*.04+(on?0:.3);rig.upper.rotation.x=on?0:.08;rig.root.position.y=Math.sin(t*2+ph)*(on?.008:0);
  r.setSize(canvas.clientWidth,canvas.clientHeight,false);cam.aspect=canvas.clientWidth/canvas.clientHeight;cam.updateProjectionMatrix();r.render(sc,cam)});
}
AGENTS.forEach(a=>{const c=document.createElement('div');c.className='card';c.style.setProperty('--c',a.color);
 c.innerHTML='<span class="chair"></span><div class="win"><canvas></canvas></div><div class="name"><i></i>@'+a.name+'</div><div class="role">'+a.provider+(a.role?' - '+a.role:'')+'</div>';
 c.onclick=()=>{sel.has(a.name)?sel.delete(a.name):sel.add(a.name);draw()};grid.append(c);a.el=c;
 try{bust(a,c.querySelector('canvas'))}catch(e){c.querySelector('.win').textContent=''}});
function draw(){AGENTS.forEach(a=>{const on=sel.has(a.name);a.el.classList.toggle('on',on);a.el.querySelector('.chair').textContent=on?'SEATED':'EMPTY'});$('go').disabled=!sel.size}
$('all').onclick=()=>{sel.size===AGENTS.length?sel.clear():AGENTS.forEach(a=>sel.add(a.name));draw()};
(function loop(t){busts.forEach(b=>b(t/1000));requestAnimationFrame(loop)})(0);
$('go').onclick=async()=>{const names=AGENTS.map(a=>a.name).filter(n=>sel.has(n));
 localStorage.setItem(KEY,JSON.stringify(names));$('go').disabled=true;$('go').textContent='Starting...';
 await fetch('/select'+Q,{method:'POST',body:JSON.stringify(names)});
 for(;;){await new Promise(r=>setTimeout(r,400));
  try{const r=await fetch('/'+Q,{cache:'no-store'});const x=await r.text();
   if(r.ok&&!x.includes('Who joins this meeting')){location.replace('/'+Q);return}}catch(e){}}};
draw();
</script></body></html>"""


def pick_agents(agents: list[dict], port: int, token: str, open_url=None) -> list[str]:
    """Serve the picker on 127.0.0.1:port until a selection is posted; return the chosen names."""
    done = threading.Event()
    chosen: list[str] = []
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    info = [{"name": a["name"], "provider": a.get("provider", ""), "color": a.get("color", "#888"),
             "role": a.get("role", ""), "face": agent_face(a)} for a in agents]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok(self):
            q = parse_qs(urlparse(self.path).query)
            t = (q.get("t") or [""])[0]
            return self.headers.get("Host") in hosts and secrets.compare_digest(t, token)

        def do_GET(self):
            if not self._ok():
                self.send_response(403); self.end_headers(); return
            path = urlparse(self.path).path
            f = None
            if path in ASSETS:
                f, ct = STATIC / path.lstrip("/"), ASSETS[path]
            elif path.startswith("/faces/face_") and path.endswith(".png") and "/" not in path[7:]:
                f, ct = STATIC / path.lstrip("/"), "image/png"
            if f is not None:
                if not f.is_file():
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header("Content-Type", ct); self.end_headers()
                self.wfile.write(f.read_bytes()); return
            body = (PAGE.replace("__AGENTS__", json.dumps(info).replace("</", "<\\/"))
                    .replace("__TOKEN__", json.dumps(token)).replace("__CHAR__", _char_source())).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            if not self._ok() or self.headers.get("Origin") not in {f"http://{h}" for h in hosts}:
                self.send_response(403); self.end_headers(); return
            try:
                names = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                valid = {a["name"] for a in agents}
                names = [n for n in names if n in valid]
            except Exception:
                names = []
            if not names:
                self.send_response(400); self.end_headers(); return
            chosen.extend(names)
            self.send_response(204); self.end_headers()
            done.set()

    class S(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = S(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_url:
        open_url()
    done.wait()
    srv.shutdown(); srv.server_close()
    return chosen
