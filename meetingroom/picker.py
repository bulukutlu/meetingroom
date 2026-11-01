"""The corridor: the hub's start page. Every open room is a wooden door (step in, or
close it); the door at the end sets up a new room - who joins and where it works."""
from __future__ import annotations

import json
from pathlib import Path

from .agents import agent_face
from .location import ssh_hosts

STATIC = Path(__file__).parent / "static"


def _char_source() -> str:
    """The room's own buildChar() (same body), lifted from room3d.js so the picker never drifts from it."""
    src = (STATIC / "room3d.js").read_text()
    a, b = src.index("const B = {"), src.index("// ---------------------------------------------------------------- homography")
    return src[a:b].replace('new URL("./faces/" + face.file, import.meta.url).href', '"/static/faces/" + face.file')

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Meeting room - corridor</title><link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
<style>
 :root{--bg:#120d09;--panel:#1b1510;--panel2:#241c15;--line:#352a1f;--line2:#46382a;--text:#efe6d6;--muted:#a8977f;--dim:#76664f;--amber:#f0b44a;--accent:#9fe38f}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--text);background:#0e0907;overflow-x:hidden}
 h1{font:700 13px ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;margin:0 0 6px;color:var(--amber)}
 h2{font-size:26px;font-weight:600;margin:0 0 6px} p.sub{color:var(--muted);margin:0 0 30px}
 /* ---- corridor */
 /* ---- same chrome as the room page: mono header bar, hard pixels, black-bordered tags */
 :root{--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--red:#e56b5b;--green:#7fd36f}
 body{display:grid;grid-template-rows:44px minmax(0,1fr);height:100vh;overflow:hidden}
 body.setup{display:block;height:auto;overflow:auto}
 header.hbar{display:flex;align-items:center;gap:14px;padding:0 16px;border-bottom:1px solid var(--line);background:var(--panel);font-family:var(--mono)}
 .brand{display:flex;align-items:center;gap:9px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;font-size:13px}
 .rec{width:9px;height:9px;background:var(--red);box-shadow:0 0 0 3px #e56b5b33}
 .meta{color:var(--dim);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .spacer{flex:1}
 .conn{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:11px}.conn i{width:8px;height:8px;background:var(--dim)}.conn.on i{background:var(--green)}
 header.hbar button{font:600 11.5px var(--mono);color:var(--text);background:#2f5a2a;border:2px solid #000;padding:4px 10px;cursor:pointer;box-shadow:2px 2px 0 #000}
 header.hbar button:hover{background:#3a6e33}
 #game{position:relative;overflow:hidden;background:#1a120c}
 #cv{display:block;image-rendering:pixelated}
 #labels{position:absolute;inset:0;pointer-events:none;overflow:hidden}
 .lbl{position:absolute;left:0;top:0;display:flex;flex-direction:column;align-items:center;gap:5px;font-family:var(--mono);will-change:transform}
 .lbl .tag{display:flex;align-items:center;gap:6px;background:#0e0a07cc;border:2px solid #000;padding:2px 7px;font-size:12px;color:#efe6d6;white-space:nowrap;max-width:220px}
 .lbl .tag b{overflow:hidden;text-overflow:ellipsis}
 .lbl .tag i{width:8px;height:8px;flex:none}
 .lbl .tag span{color:var(--muted);font-size:11px}
 .lbl .tag .x{display:none;background:#5a2620;color:#ffd0c8;border:1px solid #000;font:700 10px var(--mono);padding:0 5px;cursor:pointer;margin-left:2px}
 .lbl.hot .tag{border-color:#f0b44a;background:#1b1510ee}.lbl.hot .tag .x{display:inline-block}
 .lbl .cap{font-size:10.5px;color:var(--muted);background:#0e0a0799;padding:1px 6px;white-space:nowrap;max-width:240px;overflow:hidden;text-overflow:ellipsis}
 .hint{position:absolute;left:12px;bottom:10px;font:11px var(--mono);color:var(--dim);background:#0e0a0799;padding:2px 7px;pointer-events:none}
 #empty{position:absolute;left:50%;top:18px;transform:translateX(-50%);font:12px var(--mono);color:var(--muted);background:#0e0a07cc;border:2px solid #000;padding:4px 10px;pointer-events:none}
 /* the setup screen in the room's style: square corners, black borders, hard shadows */
 #setup .card,#setup .where,#setup .qty button,#setup .wbtn,#setup .seg,#setup .wrow input,#setup .browser,#setup .recent span,#setup .card .win,#setup .chair{border-radius:0}
 #setup .card,#setup .where{border:2px solid #000;box-shadow:4px 4px 0 #000;background:var(--panel)}
 #setup .card.on{border-color:var(--c);box-shadow:4px 4px 0 #000,0 0 22px -6px var(--c)}
 #setup h1,#setup .where h3,#setup .card .name{font-family:var(--mono)}
 #setup .go{background:#2f5a2a;color:var(--text);border:2px solid #000;border-radius:0;font:700 14px var(--mono);box-shadow:3px 3px 0 #000;text-transform:uppercase}
 #setup .go:active{transform:translate(2px,2px);box-shadow:1px 1px 0 #000}
 #setup .link{font-family:var(--mono);font-size:12px}
 /* ---- setting up a new room */
 #setup{display:none;min-height:100vh;flex-direction:column;align-items:center;padding:5vh 20px 40px;background:var(--bg)}
 body.setup #game,body.setup header.hbar,body.sett #game,body.sett header.hbar{display:none} body.setup #setup{display:flex}
 #sett{display:none;min-height:100vh;flex-direction:column;align-items:center;padding:5vh 20px 40px;background:var(--bg)} body.sett #sett{display:flex} body.sett{display:block;height:auto;overflow:auto}
 #sett .where{width:min(560px,100%);box-sizing:border-box;border:2px solid #000;box-shadow:4px 4px 0 #000;background:var(--panel);padding:14px 16px;margin-bottom:14px;font-family:var(--mono)}
 #sett h3{margin:0 0 8px;font:700 12px var(--mono);color:var(--amber);letter-spacing:.1em;text-transform:uppercase} #sett label.t{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px;color:var(--text)} #sett .d{color:var(--dim);font-size:11px;margin:-3px 0 6px 26px} #sett input[type=range]{flex:1}
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
 .qty{display:flex;align-items:center;gap:6px;margin-top:8px}.qty span{flex:1;text-align:center;font-size:12px;color:var(--muted)}
 .qty button{background:#2e241b;color:var(--text);border:2px solid #000;border-radius:6px;font:600 12px system-ui;padding:4px 9px;cursor:pointer}.qty button:hover{background:#3a2e22}
 .bar{margin-top:30px;display:flex;gap:14px;align-items:center}
 .go{padding:12px 30px;background:var(--amber);color:#1a120c;border:0;border-radius:8px;font:700 15px system-ui;cursor:pointer;box-shadow:0 4px 0 #8a5f1c}
 .go:active{transform:translateY(3px);box-shadow:0 1px 0 #8a5f1c}.go:disabled{opacity:.4;cursor:default}
 .link{color:var(--muted);font-size:13px;cursor:pointer;padding:6px 8px}.link:hover{color:var(--text)}
 .where{margin-top:30px;width:min(640px,94vw);background:linear-gradient(#241c15,#1b1510);border:2px solid var(--line2);border-radius:10px;padding:14px 16px 16px;box-shadow:0 8px 22px #0008}
 .where h3{margin:0 0 10px;font:700 12px ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
 .seg{display:flex;gap:0;border:2px solid #000;border-radius:7px;overflow:hidden;margin-bottom:12px}
 .seg button{flex:1;padding:8px 6px;background:#16100b;color:var(--muted);border:0;border-right:2px solid #000;font:600 13px system-ui;cursor:pointer}
 .seg button:last-child{border-right:0}.seg button.on{background:var(--amber);color:#1a120c}
 .wrow{display:flex;gap:8px;margin-top:8px;align-items:center}.wrow label{width:58px;color:var(--muted);font-size:12.5px}
 .wrow input{flex:1;min-width:0;background:#0e0a07;color:var(--text);border:2px solid #000;border-radius:6px;padding:8px 10px;font:13px ui-monospace,Menlo,monospace;outline:none}
 .wrow input:focus{border-color:#6a5640}
 .wbtn{padding:8px 12px;background:#2e241b;color:var(--text);border:2px solid #000;border-radius:6px;font:600 12.5px system-ui;cursor:pointer;white-space:nowrap}
 .wbtn:hover{background:#3a2e22}
 .note{color:var(--dim);font-size:12.5px;margin-top:4px}
 .browser{display:none;margin-top:8px;border:2px solid #000;border-radius:6px;background:#0e0a07;max-height:230px;overflow:auto;font:12.5px ui-monospace,Menlo,monospace}
 .browser .cur{position:sticky;top:0;background:#1b1510;padding:6px 10px;color:var(--amber);display:flex;gap:8px;align-items:center;border-bottom:1px solid var(--line)}
 .browser .cur span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .browser .d{padding:4px 10px;cursor:pointer;color:var(--text)}.browser .d:hover{background:#2a2016}
 .wst{margin-top:10px;font-size:12.5px;min-height:18px;color:var(--muted)}.wst.ok{color:var(--accent)}.wst.bad{color:#ff7b72}
 .recent{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
 .recent span{font:11.5px ui-monospace,Menlo,monospace;color:var(--muted);border:1px solid var(--line2);border-radius:5px;padding:2px 8px;cursor:pointer}
 .recent span:hover{color:var(--text);border-color:#6a5640}
</style></head><body>
<header class="hbar"><div class="brand"><span class="rec"></span>Meeting room</div><div class="meta" id="sub">corridor</div><div class="spacer"></div>
 <button id="newbtn" title="Set up a new room">+ New room</button><div class="conn on" id="conn"><i></i><span>live on this computer</span></div></header>
<div id="game"><canvas id="cv"></canvas><div id="labels"></div><div id="empty" style="display:none">No rooms yet. Step through the open door to set one up.</div>
 <div class="hint">click a door to step in · ← → or scroll to walk the corridor</div></div>
<div id="sett"><h1>&#9881; Settings</h1><h2>How the room works</h2><p class="sub">Saved in this browser; every room picks them up when it opens.</p>
<div class="where"><h3>Voice</h3>
 <label class="t"><input type="checkbox" data-s="tts"> Read replies aloud</label><div class="d">Agents' replies are spoken with the local voices.</div>
 <label class="t">Agents talking to each other <input type="range" id="avol" min="0" max="100" step="5"> <span id="avolv"></span></label><div class="d">Volume relative to speech addressed to you (100% = same as yours).</div></div>
<div class="where"><h3>Sound</h3><label class="t"><input type="checkbox" data-s="sounds"> Acknowledgements and keyboard clicks</label></div>
<div class="where"><h3>Input</h3><label class="t"><input type="checkbox" data-s="autosend"> Send voice messages automatically</label></div>
<div class="bar"><span class="link" id="sback">&larr; Back to the corridor</span></div></div>
<div id="setup"><h1>&#9679; New room</h1><h2>Who joins this meeting?</h2><p class="sub">Click a card to pull up a chair, or use + chair to seat several of the same model.</p>
<div class="grid" id="grid"></div>
<div class="where">
 <h3>Where does the meeting take place?</h3>
 <div class="seg" id="seg"><button data-k="default">Agents' own folders</button><button data-k="local">Project folder</button><button data-k="ssh">Remote over SSH</button><button data-k="saved">Previous meeting</button></div>
 <div id="wSaved" style="display:none"><div class="note">Reopen a saved meeting or recover one interrupted by a restart. Its participants, project, conversation and shared screen are restored.</div><div id="savedRooms" style="display:grid;gap:8px;margin-top:12px"></div></div>
 <div id="wDefault" class="note">Each agent works in its own folder under the meeting workspace, as before.</div>
 <div class="wrow" id="wHost"><label>Host</label><input id="host" list="hosts" placeholder="ssh alias or user@server" autocomplete="off" spellcheck="false"><button class="wbtn" id="test">Test</button></div>
 <datalist id="hosts"></datalist>
 <div class="wrow" id="wPath"><label>Folder</label><input id="path" placeholder="~/projects/analysis" autocomplete="off" spellcheck="false"><button class="wbtn" id="browse">Browse…</button></div>
 <div class="browser" id="browser"></div>
 <div class="recent" id="recent"></div>
 <div class="wst" id="wst"></div>
</div>
<div class="where"><h3>Name on the door</h3><div class="wrow" style="margin-top:0"><label>Name</label><input id="rname" placeholder="(optional, defaults to the folder name)" autocomplete="off" spellcheck="false" maxlength="60"></div></div>
<div class="bar"><span class="link" id="all">Select all / none</span><span class="link" id="back">&larr; Back to the corridor</span><button class="go" id="go">Open room</button></div>
</div>
<script type="module">
const AGENTS=__AGENTS__, T=__TOKEN__, KEY='mr-agents', Q='?t='+encodeURIComponent(T);
const THREE=await import('/static/vendor/three.min.js');
const FACES=await fetch('/static/faces/faces.json').then(r=>r.json()).catch(()=>[]);
const MAXC=4;
const cnt={};AGENTS.forEach(a=>cnt[a.name]=0);
{let saved=JSON.parse(localStorage.getItem(KEY)||'null');if(!Array.isArray(saved))saved=AGENTS.map(a=>a.name);
 saved.forEach(n=>{if(n in cnt&&cnt[n]<MAXC)cnt[n]++});
 if(!Object.values(cnt).some(v=>v))AGENTS.forEach(a=>cnt[a.name]=1)}
const total=()=>Object.values(cnt).reduce((x,y)=>x+y,0);
const $=id=>document.getElementById(id), grid=$('grid'), busts=[];
let built=false;
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
 busts.push(t=>{const on=cnt[a.name]>0;rig.root.rotation.y=Math.sin(t*.7+ph)*(on?.5:.2);
  rig.head.rotation.x=Math.sin(t*1.1+ph)*.04+(on?0:.3);rig.upper.rotation.x=on?0:.08;rig.root.position.y=Math.sin(t*2+ph)*(on?.008:0);
  r.setSize(canvas.clientWidth,canvas.clientHeight,false);cam.aspect=canvas.clientWidth/canvas.clientHeight;cam.updateProjectionMatrix();r.render(sc,cam)});
}
function buildCards(){if(built)return;built=true;
AGENTS.forEach(a=>{const c=document.createElement('div');c.className='card';c.style.setProperty('--c',a.color);
 c.innerHTML='<span class="chair"></span><div class="win"><canvas></canvas></div><div class="name"><i></i>@'+a.name+'</div><div class="role">'+a.provider+(a.role?' - '+a.role:'')+'</div><div class="qty"><button data-d="-1" title="Remove a chair">&minus;</button><span></span><button data-d="1" title="Add another chair for this model">+ chair</button></div>';
 c.onclick=e=>{const b=e.target.closest('[data-d]');
  if(b){const n=cnt[a.name]+ +b.dataset.d;if(n>=0&&n<=MAXC&&total()+ +b.dataset.d<=12)cnt[a.name]=n}
  else cnt[a.name]=cnt[a.name]?0:1;
  draw()};grid.append(c);a.el=c;
 try{bust(a,c.querySelector('canvas'))}catch(e){c.querySelector('.win').textContent=''}});
draw()}
function draw(){if(!built)return;AGENTS.forEach(a=>{const n=cnt[a.name],on=n>0;a.el.classList.toggle('on',on);a.el.querySelector('.chair').textContent=on?(n>1?n+' CHAIRS':'SEATED'):'EMPTY';a.el.querySelector('.qty span').textContent=n+(n===1?' chair':' chairs')});
 $('go').disabled=!total();$('go').textContent='Open room ('+total()+' seated)'}
$('all').onclick=()=>{const any=total()>0;AGENTS.forEach(a=>cnt[a.name]=any?0:1);draw()};
(function loop(t){if(document.body.classList.contains('setup'))busts.forEach(b=>b(t/1000));requestAnimationFrame(loop)})(0);
$('go').onclick=async()=>{const names=AGENTS.flatMap(a=>Array(cnt[a.name]).fill(a.name)), w=where();
 if(w.kind!=='default'&&!w.path&&w.kind==='local'){status('Choose a project folder (or pick “Agents’ own folders”).','bad');return}
 if(w.kind==='ssh'&&!w.host){status('Enter an SSH host.','bad');return}
 localStorage.setItem(KEY,JSON.stringify(names));$('go').disabled=true;$('go').textContent=w.kind==='ssh'?'Connecting...':'Starting...';
 const res=await fetch('/select'+Q,{method:'POST',body:JSON.stringify({agents:names,location:w,name:$('rname').value.trim()})});
 if(!res.ok){const j=await res.json().catch(()=>({}));status(j.error||'Could not start ('+res.status+')','bad');$('go').disabled=false;draw();return}
 const j=await res.json().catch(()=>({}));if(j.location)Object.assign(w,j.location);
 localStorage.setItem(WKEY,JSON.stringify(w));
 if(w.kind!=='default'){const rec=JSON.parse(localStorage.getItem(RKEY)||'[]').filter(r=>!(r.kind===w.kind&&r.path===w.path&&(r.host||'')===(w.host||'')));
  rec.unshift({kind:w.kind,path:w.path,host:w.host});localStorage.setItem(RKEY,JSON.stringify(rec.slice(0,8)))}
 location.href=j.url};
// ---- where: agents' folders | local project folder | remote over SSH
const WKEY='mr-where', RKEY='mr-where-recent', HOSTS=__HOSTS__;
let W=Object.assign({kind:'default',path:'',host:''},JSON.parse(localStorage.getItem(WKEY)||'{}'));
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('hosts').innerHTML=HOSTS.map(h=>'<option value="'+esc(h)+'">').join('');
$('host').value=W.host;$('path').value=W.path;
function status(t,c){$('wst').textContent=t||'';$('wst').className='wst '+(c||'')}
function drawWhere(){
 const recovering=W.kind==='saved';
 $('wSaved').style.display=recovering?'':'none';
 $('grid').style.display=recovering?'none':'';
 $('all').style.display=recovering?'none':'';
 $('go').style.display=recovering?'none':'';
 $('rname').closest('.where').style.display=recovering?'none':'';
 document.querySelector('#setup h2').textContent=recovering?'Continue a previous meeting':'Who joins this meeting?';
 document.querySelector('#setup p.sub').style.display=recovering?'none':'';
 if(recovering)loadSaved();
 [...$('seg').children].forEach(b=>b.classList.toggle('on',b.dataset.k===W.kind));
 $('wDefault').style.display=W.kind==='default'?'':'none';$('wHost').style.display=W.kind==='ssh'?'':'none';
 $('wPath').style.display=W.kind==='default'||recovering?'none':'';if(W.kind==='default'||recovering)$('browser').style.display='none';
 $('path').placeholder=W.kind==='ssh'?'~ (remote home) or /path/on/server':'~/projects/analysis';
 const rec=(JSON.parse(localStorage.getItem(RKEY)||'[]')).filter(r=>r.kind===W.kind);
 $('recent').innerHTML=rec.map((r,i)=>'<span data-r="'+i+'" title="Use this again">'+esc(r.kind==='ssh'?r.host+':'+r.path:r.path)+'</span>').join('');
 $('recent').onclick=e=>{const t=e.target.closest('[data-r]');if(!t)return;const r=rec[+t.dataset.r];
  $('path').value=r.path;$('host').value=r.host||'';status('');$('browser').style.display='none'};
}
async function loadSaved(){
 const box=$('savedRooms');box.textContent='Loading saved meetings…';
 try{
  const r=await fetch('/api/saved'+Q);if(!r.ok)throw Error('Could not load saved meetings');
  const rooms=(await r.json()).rooms;
  box.textContent=rooms.length?'':'No saved meetings yet. Close a room and choose to save it for later.';
  rooms.forEach(room=>{const b=document.createElement('button');b.className='wbtn';b.style.cssText='text-align:left;white-space:normal';
   b.textContent=room.title+' · '+new Date(room.updated*1000).toLocaleString()+' · '+room.agents.map(n=>'@'+n).join(', ')+(room.status==='recovery'?' · recovery checkpoint':'');
   b.onclick=async()=>{box.querySelectorAll('button').forEach(x=>x.disabled=true);status('Reopening meeting…');
    try{const res=await fetch('/api/restore'+Q,{method:'POST',body:JSON.stringify({session:room.id})});const j=await res.json();if(!res.ok)throw Error(j.error||'Could not reopen meeting');location.href=j.url}
    catch(e){status(e.message,'bad');box.querySelectorAll('button').forEach(x=>x.disabled=false)}};
   box.append(b)});
 }catch(e){box.textContent=e.message}
}
$('seg').onclick=e=>{const b=e.target.closest('[data-k]');if(b){W.kind=b.dataset.k;status('');drawWhere()}};
const where=()=>({kind:W.kind,path:$('path').value.trim(),host:W.kind==='ssh'?$('host').value.trim():''});
async function api(p,body){const r=await fetch(p+Q,body?{method:'POST',body:JSON.stringify(body)}:{});return r.json().catch(()=>({error:'HTTP '+r.status}))}
async function browse(path){
 const w=where(),b=$('browser');if(W.kind==='ssh'&&!w.host){status('Enter a host first.','bad');return}
 b.style.display='block';b.innerHTML='<div class="cur"><span>'+(W.kind==='ssh'?'connecting to '+esc(w.host)+'…':'loading…')+'</span></div>';
 const r=await api('/ls',{path:path??(w.path||'~'),host:w.host});
 if(r.error){b.innerHTML='<div class="cur"><span>'+esc(r.error)+'</span></div>';return}
 b.innerHTML='<div class="cur"><span title="'+esc(r.path)+'">'+esc((w.host?w.host+':':'')+r.path)+'</span><button class="wbtn" data-use>Use this folder</button></div>'+
  (r.path!==r.parent?'<div class="d" data-p="'+esc(r.parent)+'">..</div>':'')+r.dirs.map(d=>'<div class="d" data-p="'+esc(r.path.replace(/\\/$/,'')+'/'+d)+'">'+esc(d)+'/</div>').join('');
 b.onclick=e=>{const d=e.target.closest('[data-p]');if(d)return browse(d.dataset.p);
  if(e.target.closest('[data-use]')){$('path').value=r.path;b.style.display='none';status('')}};
 $('path').value=r.path;
}
$('browse').onclick=()=>$('browser').style.display==='block'?($('browser').style.display='none'):browse();
$('test').onclick=async()=>{const w=where();if(!w.host)return status('Enter a host first.','bad');
 status('Connecting to '+w.host+'…');const r=await api('/probe',w);
 if(!r.ok)return status(r.error,'bad');$('path').value=r.path;
 const b=r.bins;status('✓ '+r.host+':'+r.path+'  ·  claude '+(b.claude?'✓':'✗ missing')+'  ·  codex '+(b.codex?'✓':'✗ missing'),'ok')};
drawWhere();

// ---- the corridor: one wooden door per open room (3D, same style as the room), plus a door to a new one
function openSetup(){buildCards();document.body.classList.add('setup');scrollTo(0,0);status('');drawWhere()}
function closeSetup(){document.body.classList.remove('setup')}
const SD={tts:0,sounds:1,autosend:0};
function openSett(){document.body.classList.add('sett');scrollTo(0,0);
 document.querySelectorAll('#sett [data-s]').forEach(c=>{const v=localStorage.getItem('mr_'+c.dataset.s);c.checked=v===null?!!SD[c.dataset.s]:v==='1';c.onchange=()=>localStorage.setItem('mr_'+c.dataset.s,c.checked?'1':'0')});
 const r=$('avol'),v=localStorage.getItem('mr_agentvol');r.value=Math.round((v===null?.55:+v)*100);$('avolv').textContent=r.value+'%';
 r.oninput=()=>{$('avolv').textContent=r.value+'%';localStorage.setItem('mr_agentvol',r.value/100)}}
const closeSett=()=>document.body.classList.remove('sett');$('sback').onclick=closeSett;
$('back').onclick=closeSetup;$('newbtn').onclick=openSetup;
addEventListener('keydown',e=>{if(e.key==='Escape'){closeSetup();closeSett()}});
let ROOMS=[],hall=null;
try{const {createCorridor}=await import('/static/corridor3d.js');
 hall=createCorridor({wrap:$('game'),canvas:$('cv'),labels:$('labels'),
  onPick:p=>p.kind==='new'?openSetup():p.kind==='settings'?openSett():location.href='/r/'+p.id+'/'+Q,
  onClose:async r=>{if(!confirm('Close "'+r.title+'"? Its agents will stop.'))return;
   const save=confirm('Save this meeting’s status for later? OK saves participants, conversation and shared screen. Cancel closes without a resumable save; minutes are kept.');
   const res=await fetch('/api/close/'+r.id+Q,{method:'POST',body:JSON.stringify({save})});if(!res.ok)alert('Could not close and save the meeting. Please try again.');refresh()}})}
catch(e){$('empty').style.display='';$('empty').textContent='3D view unavailable ('+e.message+'). Use + New room.'}
async function refresh(){
 const c=$('conn');
 try{const r=await fetch('/api/rooms'+Q,{cache:'no-store'});if(!r.ok)throw 0;ROOMS=(await r.json()).rooms;c.className='conn on';c.lastChild.textContent='live on this computer'}
 catch(e){c.className='conn';c.lastChild.textContent='app not running';return}
 hall&&hall.setRooms(ROOMS);
 $('sub').textContent='corridor · '+(ROOMS.length?ROOMS.length+(ROOMS.length>1?' rooms open':' room open'):'no rooms open yet');
 if(hall)$('empty').style.display=ROOMS.length?'none':'';
}
refresh();setInterval(()=>{if(!document.body.classList.contains('setup'))refresh()},2500);
if(new URLSearchParams(location.search).get('new'))openSetup();
</script></body></html>"""


def lobby_page(agents: list[dict], token: str) -> str:
    info = [{"name": a["name"], "provider": a.get("provider", ""), "color": a.get("color", "#888"),
             "role": a.get("role", ""), "face": agent_face(a)} for a in agents]
    return (PAGE.replace("__AGENTS__", json.dumps(info).replace("</", "<\\/"))
            .replace("__TOKEN__", json.dumps(token)).replace("__HOSTS__", json.dumps(ssh_hosts()).replace("</", "<\\/"))
            .replace("__CHAR__", _char_source()))
