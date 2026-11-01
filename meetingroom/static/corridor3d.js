// The corridor outside the meeting rooms, in the same low-poly, low-resolution style as
// room3d.js (same palette, plank floor, red rug, warm lamps, hard pixels). One wooden door
// per open room plus a door standing ajar that leads to a new one. Renders only when
// something changes (or a status lamp is pulsing) to keep the CPU quiet.
import * as THREE from "./vendor/three.min.js";

const PIX = 3;                         // size of one "game pixel" in CSS pixels (chunkier than the room: the corridor is simpler)
const SPACING = 2.0, DW = 1.0, DH = 2.15, WALL_Z = -1.0;
export const LAMP = { idle: "#ffd27a", busy: "#7fd36f", ask: "#f0b44a", new: "#7dff9a" };

const mat = (c, extra = {}) => new THREE.MeshLambertMaterial({ color: c, flatShading: true, ...extra });
function box(w, h, d, m, x = 0, y = 0, z = 0, parent) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof m === "number" ? mat(m) : m);
  mesh.position.set(x, y, z);
  if (parent) parent.add(mesh);
  return mesh;
}
function canvasTex(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.magFilter = t.minFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function dispose(o) {
  o.traverse(m => { if (m.geometry) m.geometry.dispose(); if (m.material) { if (m.material.map) m.material.map.dispose(); m.material.dispose(); } });
}
export const lampOf = r => r.approvals ? "ask" : r.agents.some(a => a.status === "thinking" || a.status === "working") ? "busy" : "idle";

const painting = (a, b) => canvasTex(24, 16, (g, w, h) => {
  g.fillStyle = a; g.fillRect(0, 0, w, h); g.fillStyle = b; g.fillRect(0, h * 0.62, w, h); g.fillStyle = "#2a3a20";
  for (let i = 0; i < 4; i++) { g.beginPath(); g.moveTo(i * 6 + 2, h * 0.65); g.lineTo(i * 6 + 5, h * 0.3); g.lineTo(i * 6 + 8, h * 0.65); g.fill(); }
  g.fillStyle = "#3a5a7a"; g.fillRect(2, h * 0.8, w - 6, 2);
});
// frosted door glass with the blurred shapes of whoever sits inside
const glass = agents => canvasTex(24, 20, (g, w, h) => {
  g.fillStyle = "#d9a25a"; g.fillRect(0, 0, w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if ((x * 7 + y * 3) % 5 === 0) { g.fillStyle = (x + y) % 2 ? "#e8b870" : "#c98f48"; g.fillRect(x, y, 1, 1); }
  const n = Math.min(agents.length, 6), step = w / (n + 1);
  agents.slice(0, 6).forEach((a, i) => {
    const cx = Math.round(step * (i + 1)), c = a.color || "#888";
    g.globalAlpha = a.status === "thinking" || a.status === "working" ? 0.95 : 0.7; g.fillStyle = c;
    g.fillRect(cx - 1, 6, 3, 3); g.fillRect(cx - 2, 10, 5, 8);
  });
  g.globalAlpha = 1;
});
const woodTex = () => canvasTex(16, 32, (c, w, h) => {                                      // coarse door grain
  c.fillStyle = "#7a4a28"; c.fillRect(0, 0, w, h);
  for (let x = 0; x < w; x++) for (let y = 0; y < h; y++) { const k = (x * 5 + Math.floor(y / 6) * 3 + (y * 7 >> 3)) % 9;
    if (k === 0) { c.fillStyle = "#6a3e20"; c.fillRect(x, y, 1, 1); } else if (k === 4) { c.fillStyle = "#86542e"; c.fillRect(x, y, 1, 1); } }
});
const gearTex = () => canvasTex(24, 20, (g, w, h) => {
  g.fillStyle = "#2a3a5a"; g.fillRect(0, 0, w, h); g.fillStyle = "#8fb4ff";
  for (let a = 0; a < 8; a++) { const t = a * Math.PI / 4; g.fillRect(Math.round(12 + Math.cos(t) * 6.5) - 1, Math.round(10 + Math.sin(t) * 6.5) - 1, 3, 3); }
  g.beginPath(); g.arc(12, 10, 5, 0, 7); g.fill(); g.fillStyle = "#2a3a5a"; g.beginPath(); g.arc(12, 10, 2, 0, 7); g.fill();
});
const signTex = text => canvasTex(48, 12, (g, w, h) => {
  g.fillStyle = "#0f3b1e"; g.fillRect(0, 0, w, h); g.fillStyle = "#7dff9a"; g.font = "bold 8px monospace";
  g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, w / 2, h / 2 + 1);
});

function buildShell(L) {
  const g = new THREE.Group(), W = L + 16, cx = L / 2;
  const plank = canvasTex(64, 64, (c) => {
    c.fillStyle = "#6b4426"; c.fillRect(0, 0, 64, 64);
    for (let i = 0; i < 8; i++) { c.fillStyle = i % 2 ? "#5f3b20" : "#73492a"; c.fillRect(0, i * 8, 64, 7); c.fillStyle = "#4a2d17"; c.fillRect((i * 23) % 64, i * 8, 1, 7); }
  });
  plank.wrapS = plank.wrapT = THREE.RepeatWrapping; plank.repeat.set(W / 1.6, 4);
  box(W, 0.1, 7, mat(0xffffff, { map: plank }), cx, -0.05, 2.4, g);                        // floor
  const runner = canvasTex(32, 24, (c, w, h) => {                                             // long red runner, same weave as the room's rug
    c.fillStyle = "#5a1414"; c.fillRect(0, 0, w, h); c.fillStyle = "#c9a14a"; c.fillRect(0, 2, w, h - 4);
    c.fillStyle = "#7d1f1f"; c.fillRect(0, 3, w, h - 6);
    for (let y = 5; y < h - 5; y++) for (let x = 0; x < w; x++) { c.fillStyle = (x + y) % 4 === 0 ? "#8e2727" : (x * 3 + y) % 7 === 0 ? "#6a1818" : "#7d1f1f"; c.fillRect(x, y, 1, 1); }
  });
  runner.wrapS = THREE.RepeatWrapping; runner.repeat.set(W / 1.2, 1);
  box(W, 0.02, 1.5, mat(0xffffff, { map: runner }), cx, 0.01, 0.55, g);
  const paper = canvasTex(16, 16, (c, w, h) => {                                              // faded striped wallpaper
    c.fillStyle = "#a89268"; c.fillRect(0, 0, w, h); c.fillStyle = "#9c865c"; c.fillRect(0, 0, 3, h); c.fillRect(8, 0, 1, h);
    c.fillStyle = "#b29c72"; for (let y = 2; y < h; y += 5) c.fillRect(12, y, 1, 1);
  });
  paper.wrapS = paper.wrapT = THREE.RepeatWrapping; paper.repeat.set(W / 0.6, 3.4 / 0.6);
  box(W, 3.4, 0.1, mat(0xffffff, { map: paper }), cx, 1.7, WALL_Z - 0.05, g);                // wall
  box(W, 0.95, 0.04, 0x6a4226, cx, 0.47, WALL_Z + 0.02, g);                                  // wainscot
  box(W, 0.06, 0.08, 0x4e3119, cx, 0.96, WALL_Z + 0.03, g);                                  // dado rail
  box(W, 0.12, 0.06, 0x5a3a20, cx, 0.06, WALL_Z + 0.05, g);                                  // skirting
  box(W, 0.1, 7, 0x2a1a10, cx, 3.4, 2.4, g);                                                 // ceiling
  for (let x = -2; x <= L + 2; x += SPACING * 1.5) {                                         // ceiling fixtures
    box(0.6, 0.05, 0.25, new THREE.MeshBasicMaterial({ color: 0xffe9b8 }), x + SPACING / 2, 3.33, 0.6, g);
  }
  // pictures between the doors, and a plant at either end
  const pics = [["#7a8a9a", "#7a7a4a"], ["#9a8a6a", "#6a6a3a"], ["#8a7a9a", "#5a6a3a"]];
  for (let i = -1; i * SPACING <= L + 0.01; i++) {
    const x = i * SPACING + SPACING / 2, [a, b] = pics[(i + 3) % pics.length];
    box(0.62, 0.46, 0.05, 0x5a3218, x, 1.75, WALL_Z + 0.02, g);
    box(0.5, 0.34, 0.02, mat(0xffffff, { map: painting(a, b) }), x, 1.75, WALL_Z + 0.05, g);
  }
  [-SPACING * 1.1, L + SPACING * 1.1].forEach(x => {
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.4, 6), mat(0x8a4a2a)); pot.position.set(x, 0.2, WALL_Z + 0.35); g.add(pot);
    for (let i = 0; i < 8; i++) { const l = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.7, 4), mat(i % 2 ? 0x2f6a2a : 0x3f7f34));
      l.position.set(x + Math.cos(i) * 0.12, 0.7, WALL_Z + 0.35 + Math.sin(i) * 0.12); l.rotation.set(Math.sin(i) * 0.6, 0, Math.cos(i) * 0.6); g.add(l); }
  });
  return g;
}

function buildDoor(i, room, kind) {
  const g = new THREE.Group(); g.position.set(i * SPACING, 0, WALL_Z);
  const isNew = kind === "new", isSet = kind === "settings", isRoom = !isNew && !isSet;
  box(DW + 0.18, DH + 0.1, 0.08, 0x4e3119, 0, (DH + 0.1) / 2, 0.02, g);                     // frame
  box(DW, DH, 0.02, new THREE.MeshBasicMaterial({ color: isNew ? 0xffcf7a : isSet ? 0x8fb4ff : 0x1a100a }), 0, DH / 2, 0.065, g);   // doorway behind the leaf
  const hinge = new THREE.Group(); hinge.position.set(-DW / 2, 0, 0.09); g.add(hinge);
  const leafMat = mat(0xffffff, { map: woodTex() }); leafMat.emissive = new THREE.Color(0x000000);
  box(DW - 0.03, DH - 0.03, 0.05, leafMat, DW / 2, DH / 2, 0, hinge);
  box(0.66, 0.72, 0.02, 0x6a3f20, DW / 2, 0.55, 0.03, hinge);                                // lower panel
  if (isNew) box(0.66, 0.6, 0.02, 0x6a3f20, DW / 2, 1.5, 0.03, hinge);
  else if (isSet) box(0.62, 0.52, 0.02, new THREE.MeshBasicMaterial({ map: gearTex() }), DW / 2, 1.52, 0.035, hinge);
  else box(0.62, 0.52, 0.02, new THREE.MeshBasicMaterial({ map: glass(room.agents) }), DW / 2, 1.52, 0.035, hinge);   // frosted window
  box(0.08, 0.06, 0.08, 0xd9b45a, DW - 0.12, 1.02, 0.06, hinge);                            // handle
  let lampMat = null, light = null;
  if (isSet) {
    box(0.62, 0.16, 0.04, new THREE.MeshBasicMaterial({ map: signTex("SETTINGS") }), 0, DH + 0.22, 0.04, g);
    light = new THREE.PointLight(0x8fb4ff, 1.0, 3.0, 1.6); light.position.set(0.15, 1.5, 0.3); g.add(light);
  } else if (isNew) {
    box(0.62, 0.16, 0.04, new THREE.MeshBasicMaterial({ map: signTex("NEW ROOM") }), 0, DH + 0.22, 0.04, g);
    light = new THREE.PointLight(0xffc36a, 1.4, 3.0, 1.6); light.position.set(0.15, 1.5, 0.3); g.add(light);
  } else {
    lampMat = new THREE.MeshBasicMaterial({ color: LAMP[lampOf(room)] });
    box(0.34, 0.09, 0.12, lampMat, 0, DH + 0.24, 0.08, g);                                  // status lamp over the door
    box(0.4, 0.03, 0.14, 0x3a2412, 0, DH + 0.18, 0.08, g);
    light = new THREE.PointLight(new THREE.Color(LAMP[lampOf(room)]), 1.0, 2.6, 1.6); light.position.set(0, DH + 0.1, 0.45); g.add(light);
  }
  const pick = isNew ? { kind: "new" } : isSet ? { kind: "settings" } : { kind: "room", id: room.id };
  g.traverse(o => { if (o.isMesh) o.userData.pick = pick; });
  const base = isNew || isSet ? -0.5 : 0;
  hinge.rotation.y = base;
  return { g, hinge, leafMat, lampMat, light, pick, base, angle: base, room, state: isNew ? "new" : isSet ? "settings" : lampOf(room) };
}

export function createCorridor({ wrap, canvas, labels, onPick = () => {}, onClose = () => {} }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(1);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a120c);
  scene.fog = new THREE.Fog(0x1a120c, 7, 15);
  scene.add(new THREE.HemisphereLight(0xffdcae, 0x3a2716, 1.15));
  const camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.05, 40);
  let shell = null, shellLen = -1, doors = [], camX = 0, camTarget = 0, span = 0, hover = null, opening = null, sig = "";
  let dirty = true, lastFrame = 0;

  function resize() {
    const r = wrap.getBoundingClientRect();
    renderer.setSize(Math.max(1, Math.round(r.width / PIX)), Math.max(1, Math.round(r.height / PIX)), false);
    canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
    camera.aspect = r.width / Math.max(1, r.height); camera.updateProjectionMatrix();
    dirty = true;
  }
  new ResizeObserver(resize).observe(wrap); resize();

  function setRooms(rooms) {
    const s = JSON.stringify(rooms.map(r => [r.id, r.title, r.label, r.messages, r.approvals, r.agents.map(a => [a.name, a.color, a.status])]));
    if (s === sig) return;
    sig = s;
    const L = (rooms.length + 1) * SPACING;
    if (L !== shellLen) { if (shell) { scene.remove(shell); dispose(shell); } shell = buildShell(L); scene.add(shell); shellLen = L; }
    doors.forEach(d => { scene.remove(d.g); dispose(d.g); d.el.remove(); });
    doors = ["settings", ...rooms, "new"].map((r, i) => {
      const kind = r === "settings" || r === "new" ? r : "room", set = r === "settings";
      if (kind !== "room") r = null;
      const d = buildDoor(i, r, kind); scene.add(d.g);
      const el = document.createElement("div"); el.className = "lbl door";
      el.innerHTML = r
        ? `<div class="tag"><i style="background:${LAMP[d.state]}"></i><b></b><span></span><button class="x" title="Close this room (its agents stop, minutes are saved)">✕</button></div><div class="cap"></div>`
        : set ? `<div class="tag"><i style="background:#8fb4ff"></i><b>Settings</b></div><div class="cap">voice, sound, behaviour</div>`
        : `<div class="tag"><i style="background:${LAMP.new}"></i><b>New room</b></div><div class="cap">pick who joins and where</div>`;
      if (r) {
        el.querySelector("b").textContent = r.title;
        el.querySelector("span").textContent = r.agents.length + " seated";
        const where = r.kind === "ssh" ? "⇄ " + r.label : r.kind === "local" ? r.label : "agents' own folders";
        el.querySelector(".cap").textContent = where + " · " + r.messages + " msgs";
        el.querySelector(".cap").title = where;
        el.querySelector(".x").onclick = e => { e.stopPropagation(); onClose(r); };
      }
      const tag = el.querySelector(".tag"); tag.style.pointerEvents = "auto"; tag.style.cursor = "pointer";
      tag.addEventListener("mouseenter", () => setHover(d)); tag.addEventListener("mouseleave", () => setHover(null));
      tag.addEventListener("click", () => pick(d));
      labels.appendChild(el); d.el = el;
      return d;
    });
    span = (rooms.length + 1) * SPACING;
    if (hover) hover = doors.find(d => d.pick.kind === hover.pick.kind && d.pick.id === hover.pick.id) || null;
    camTarget = clampX(camTarget);
    dirty = true;
  }

  // camera: far enough back to see every door if possible, otherwise scroll sideways
  const tanH = () => Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const dist = () => Math.min(7.6, Math.max(5.6, (span + SPACING * 1.2) / 2 / (tanH() * camera.aspect)));
  const visW = () => 2 * dist() * tanH() * camera.aspect;
  function clampX(x) { const room = Math.max(0, (span + SPACING) - visW()) / 2; return Math.max(-room, Math.min(room, x)); }
  wrap.addEventListener("wheel", e => { camTarget = clampX(camTarget + (e.deltaX || e.deltaY) * 0.006); dirty = true; e.preventDefault(); }, { passive: false });
  addEventListener("keydown", e => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { camTarget = clampX(camTarget + (e.key === "ArrowLeft" ? -1 : 1) * SPACING); dirty = true; } });

  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
  function hit(e) {
    const r = canvas.getBoundingClientRect();
    ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    const o = ray.intersectObjects(doors.map(d => d.g), true)[0];
    if (!o) return null;
    const p = o.object.userData.pick;
    return doors.find(d => d.pick === p) || null;
  }
  function setHover(d) {
    if (hover === d) return;
    hover = d; canvas.style.cursor = d ? "pointer" : "";
    doors.forEach(x => x.el.classList.toggle("hot", x === d));
    dirty = true;
  }
  function pick(d) {
    if (!d || opening) return;
    if (d.pick.kind === "room") { opening = d; dirty = true; setTimeout(() => onPick(d.pick), 420); }
    else onPick(d.pick);
  }
  canvas.addEventListener("pointermove", e => setHover(hit(e)));
  canvas.addEventListener("pointerleave", () => setHover(null));
  canvas.addEventListener("click", e => pick(hit(e)));

  const v = new THREE.Vector3();
  function placeLabels() {
    const r = wrap.getBoundingClientRect();
    doors.forEach(d => {
      v.set(d.g.position.x, DH + 0.5, WALL_Z).project(camera);
      const x = (v.x + 1) / 2 * r.width, y = (1 - v.y) / 2 * r.height;
      d.el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) translate(-50%,-100%)`;
      d.el.style.display = v.z < 1 && x > -200 && x < r.width + 200 ? "" : "none";
    });
  }

  function frame(t) {
    requestAnimationFrame(frame);
    const pulsing = doors.some(d => d.state === "busy" || d.state === "ask");
    let moving = Math.abs(camTarget - camX) > 0.002;
    camX += (camTarget - camX) * 0.18;
    doors.forEach(d => {
      const want = d === opening ? -1.25 : d === hover ? d.base - 0.22 : d.base;
      if (Math.abs(want - d.angle) > 0.002) { d.angle += (want - d.angle) * 0.2; d.hinge.rotation.y = d.angle; moving = true; }
      d.leafMat.emissive.setHex(d === hover ? 0x2a1a0a : 0x000000);
    });
    if (!dirty && !moving && !(pulsing && t - lastFrame > 90)) return;   // idle: no GPU work
    if (pulsing) doors.forEach(d => {
      if (d.state !== "busy" && d.state !== "ask") return;
      const k = 0.55 + 0.45 * Math.abs(Math.sin(t / (d.state === "ask" ? 260 : 520)));
      d.lampMat.color.set(LAMP[d.state]).multiplyScalar(k); d.light.intensity = 1.0 * k;
    });
    const cx = span / 2 + camX, dd = dist();
    camera.position.set(cx - 1.6, 1.85, WALL_Z + dd * 0.92);
    camera.lookAt(cx + 0.35, 1.15, WALL_Z);
    renderer.render(scene, camera);
    placeLabels();
    dirty = false; lastFrame = t;
  }
  requestAnimationFrame(frame);
  return { setRooms };
}
