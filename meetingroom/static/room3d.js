// Low-poly retro meeting room. Rendered at low resolution and scaled up with
// hard pixels; the shared-screen content is a separate, sharp DOM layer that is
// projected exactly onto the CRT glass (see screenQuad()).
import * as THREE from "./vendor/three.min.js";

const PIX = 2;                       // size of one "game pixel" in CSS pixels
const FACES = await fetch(new URL("./faces/faces.json", import.meta.url)).then(r => r.json()).catch(() => []);
const FACE_ORDER = [4, 1, 3, 5, 6, 2];   // default face per agent slot (1-based, see faces.json)
const texLoader = new THREE.TextureLoader();
const SEAT = new THREE.Vector3(0.1, 0, 0.66);
const LEAN = [new THREE.Vector3(-0.66, 0, 0.42), new THREE.Vector3(0.8, 0, 0.4), new THREE.Vector3(-1.0, 0, 0.02)];
const HOME = [new THREE.Vector3(-1.3, 0, 0.35), new THREE.Vector3(1.3, 0, 0.3), new THREE.Vector3(1.15, 0, -0.95),
              new THREE.Vector3(0.95, 0, 1.0), new THREE.Vector3(-1.6, 0, -0.75), new THREE.Vector3(0.2, 0, 1.25),
              // extra chairs for larger meetings (further out, still inside the walls)
              new THREE.Vector3(-2.5, 0, 0.9), new THREE.Vector3(2.4, 0, 0.9), new THREE.Vector3(-2.5, 0, -0.3), new THREE.Vector3(2.5, 0, -0.35),
              new THREE.Vector3(-0.7, 0, 1.75), new THREE.Vector3(1.7, 0, 1.7), new THREE.Vector3(-2.3, 0, -1.4), new THREE.Vector3(2.3, 0, -1.45)];
const homeFor = i => HOME[i % HOME.length].clone().add(new THREE.Vector3(0.25, 0, 0.2).multiplyScalar(Math.floor(i / HOME.length)));
// dozing: an idle agent nobody has talked to for a while nods off on its chair (wakes instantly when addressed)
const DOZE_AFTER_MS = (Number(new URLSearchParams(location.search).get("doze")) || 240) * 1000;   // ?doze=<seconds> to override
const PANTS = [0x2f3440, 0x3d3a34, 0x34302a, 0x2b2f36, 0x40343a, 0x303a33];

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
  t.userData.canvas = c;
  return t;
}
const hex = n => "#" + n.toString(16).padStart(6, "0");
const lerp = (a, b, k) => a + (b - a) * k;
function lerpAngle(a, b, k) { let d = ((b - a + Math.PI) % (2 * Math.PI)) - Math.PI; if (d < -Math.PI) d += 2 * Math.PI; return a + d * k; }

// ---------------------------------------------------------------- the room
// A chair whose sitter faces `yaw` (same convention as a character's yaw).
function makeChair(scene, pos, yaw) {
  const chair = new THREE.Group(); chair.position.set(pos.x, 0, pos.z); chair.rotation.y = yaw + Math.PI; scene.add(chair);
  box(0.46, 0.06, 0.44, 0x6a3c1e, 0, 0.45, 0, chair);
  box(0.46, 0.5, 0.05, 0x6a3c1e, 0, 0.75, 0.22, chair);
  [-0.19, 0.19].forEach(x => [-0.18, 0.18].forEach(z => box(0.05, 0.45, 0.05, 0x4e2c14, x, 0.22, z, chair)));
  return chair;
}

function buildRoom(scene) {
  const plank = canvasTex(64, 64, (g) => {
    g.fillStyle = "#6b4426"; g.fillRect(0, 0, 64, 64);
    for (let i = 0; i < 8; i++) { g.fillStyle = i % 2 ? "#5f3b20" : "#73492a"; g.fillRect(0, i * 8, 64, 7); g.fillStyle = "#4a2d17"; g.fillRect((i * 23) % 64, i * 8, 1, 7); }
  });
  plank.wrapS = plank.wrapT = THREE.RepeatWrapping; plank.repeat.set(6, 5);
  box(10, 0.1, 8, mat(0xffffff, { map: plank }), 0, -0.05, 0.6, scene);                 // floor
  // each room (/r/<id>) gets its own carpet colour, picked from a fixed palette by hashing the id
  const CARPETS = [["#5a1414", "#7d1f1f", "#8e2727", "#6a1818"], ["#14305a", "#1f4a7d", "#275a8e", "#183a6a"], ["#14502a", "#1f7d3f", "#278e4c", "#186a33"],
                   ["#4a1a5a", "#6e2a7d", "#7d338e", "#5a2068"], ["#5a3d14", "#8a5f1f", "#9c6d27", "#6a4818"], ["#124d52", "#1c7880", "#238b94", "#16606a"],
                   ["#5a1442", "#7d1f5e", "#8e276b", "#6a184f"], ["#3a3f48", "#58606c", "#667080", "#464c56"]];
  const rid = (location.pathname.match(/\/r\/([^/]+)/) || [])[1] || "";
  let hsh = 0; for (const ch of rid) hsh = (hsh * 31 + ch.charCodeAt(0)) >>> 0;
  const [cDark, cMid, cLight, cShade] = CARPETS[hsh % CARPETS.length];
  const rug = canvasTex(64, 48, (g, w, h) => {   // rug: dark border, gold stripe, woven centre in the room's colour
    g.fillStyle = cDark; g.fillRect(0, 0, w, h);
    g.fillStyle = "#c9a14a"; g.fillRect(3, 3, w - 6, h - 6);
    g.fillStyle = cMid; g.fillRect(4, 4, w - 8, h - 8);
    for (let y = 6; y < h - 6; y++) for (let x = 6; x < w - 6; x++) { g.fillStyle = (x + y) % 4 === 0 ? cLight : (x * 3 + y) % 7 === 0 ? cShade : cMid; g.fillRect(x, y, 1, 1); }
  });
  box(3.4, 0.02, 2.5, mat(0xffffff, { map: rug }), 0, 0.01, -0.08, scene);              // rug under the table
  box(10, 3.4, 0.1, 0xa89268, 0, 1.7, -1.95, scene);                                     // back wall
  box(0.1, 3.4, 8, 0x9c875f, -3.8, 1.7, 0.6, scene);                                     // left wall
  box(0.1, 3.4, 8, 0x9c875f, 3.8, 1.7, 0.6, scene);                                      // right wall
  box(10, 0.12, 0.06, 0x5a3a20, 0, 0.06, -1.9, scene);                                   // skirting

  // exit door on the right wall: click it to end the meeting
  const exitTex = canvasTex(32, 12, (g, w, h) => { g.fillStyle = "#0f3b1e"; g.fillRect(0, 0, w, h); g.fillStyle = "#7dff9a"; g.font = "bold 9px monospace"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("EXIT", w / 2, h / 2 + 1); });
  const door = new THREE.Group(); door.position.set(3.74, 0, -0.75); scene.add(door);
  box(0.06, 2.3, 1.1, 0x4e3119, 0, 1.15, 0, door);                                       // frame
  const doorMat = mat(0x7a4a28); doorMat.emissive = new THREE.Color(0x000000);
  box(0.05, 2.15, 0.94, doorMat, -0.03, 1.08, 0, door);                                  // leaf
  box(0.02, 0.7, 0.34, 0x6a3f20, -0.065, 1.55, 0, door); box(0.02, 0.7, 0.34, 0x6a3f20, -0.065, 0.65, 0, door);   // panels
  box(0.08, 0.06, 0.06, 0xd9b45a, -0.08, 1.05, 0.36, door);                              // handle
  box(0.04, 0.2, 0.52, new THREE.MeshBasicMaterial({ map: exitTex }), -0.04, 2.42, 0, door); // exit sign
  const doorMeshes = [];
  door.traverse(o => { if (o.isMesh) { o.userData.pick = { kind: "door" }; doorMeshes.push(o); } });
  scene.userData.doorMeshes = doorMeshes; scene.userData.doorMat = doorMat;

  // window with night sky + checkered curtains
  const night = canvasTex(48, 40, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#0d1640"); gr.addColorStop(1, "#24356b");
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    g.fillStyle = "#e8e6c8"; [[6, 5], [30, 8], [40, 3], [18, 11]].forEach(([x, y]) => g.fillRect(x, y, 1, 1));
    g.fillStyle = "#0a1022";
    for (let i = 0; i < 7; i++) { const x = i * 8 - 2, t = 18 + (i * 7) % 9; g.beginPath(); g.moveTo(x, h); g.lineTo(x + 5, t); g.lineTo(x + 10, h); g.fill(); }
  });
  box(1.4, 1.25, 0.08, 0x4e3119, -2.2, 1.75, -1.88, scene);
  box(1.22, 1.08, 0.02, new THREE.MeshBasicMaterial({ map: night }), -2.2, 1.75, -1.83, scene);
  box(0.05, 1.08, 0.05, 0x4e3119, -2.2, 1.75, -1.82, scene); box(1.22, 0.05, 0.05, 0x4e3119, -2.2, 1.75, -1.82, scene);
  const check = canvasTex(16, 16, (g) => { for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) { g.fillStyle = (x + y) % 2 ? "#e9dcc6" : "#9b2b24"; g.fillRect(x * 4, y * 4, 4, 4); } });
  check.wrapS = check.wrapT = THREE.RepeatWrapping; check.repeat.set(3, 9);
  box(0.42, 1.9, 0.06, mat(0xffffff, { map: check }), -2.95, 1.5, -1.8, scene);
  box(0.42, 1.9, 0.06, mat(0xffffff, { map: check }), -1.45, 1.5, -1.8, scene);
  box(1.9, 0.06, 0.06, 0x3a2412, -2.2, 2.48, -1.8, scene);

  // bookshelf
  const shelf = new THREE.Group(); shelf.position.set(-0.55, 0, -1.7); scene.add(shelf);
  box(0.06, 1.7, 0.35, 0x4a2b16, -0.6, 0.85, 0, shelf); box(0.06, 1.7, 0.35, 0x4a2b16, 0.6, 0.85, 0, shelf);
  box(1.26, 1.7, 0.03, 0x3a2111, 0, 0.85, -0.16, shelf);
  const bookCols = [0x7d2a22, 0x2d4a3a, 0x3a3f6b, 0x8a6a2a, 0x5a2d4a, 0x2f5a5a, 0x6b4a2a, 0x4a4a4a];
  for (let s = 0; s < 4; s++) {
    box(1.2, 0.04, 0.33, 0x4a2b16, 0, 0.05 + s * 0.42, 0, shelf);
    let x = -0.55;
    while (x < 0.5) { const w = 0.05 + ((x * 97 + s * 13) % 0.04 + 0.04) % 0.05, h = 0.25 + ((x * 31 + s) % 0.1 + 0.1) % 0.1;
      box(w, h, 0.24, bookCols[Math.floor(Math.abs(x * 50 + s * 3)) % bookCols.length], x + w / 2, 0.07 + s * 0.42 + h / 2, 0.02, shelf); x += w + 0.008; }
  }
  box(1.26, 0.04, 0.35, 0x4a2b16, 0, 1.7, 0, shelf);
  // plant on the shelf
  const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.08, 0.16, 6), mat(0x8a4a2a)); pot.position.set(0.25, 1.8, 0); shelf.add(pot);
  for (let i = 0; i < 6; i++) { const l = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.32, 4), mat(i % 2 ? 0x2f6a2a : 0x3f7f34));
    l.position.set(0.25 + Math.cos(i) * 0.07, 2.0, Math.sin(i) * 0.07); l.rotation.set(Math.sin(i) * 0.7, 0, Math.cos(i) * 0.7); shelf.add(l); }

  // wooden jukebox on top of the bookshelf: click to toggle lobby music
  const jb = new THREE.Group(); jb.position.set(-0.25, 1.72, 0); shelf.add(jb);
  const jbWood = mat(0x8a5428); jbWood.emissive = new THREE.Color(0x000000);
  box(0.36, 0.05, 0.22, 0x5a3218, 0, 0.025, 0, jb);                                       // plinth
  box(0.32, 0.2, 0.2, jbWood, 0, 0.15, 0, jb);                                            // body
  const domeG = new THREE.CylinderGeometry(0.16, 0.16, 0.2, 12, 1, false, Math.PI / 2, Math.PI); domeG.rotateX(Math.PI / 2);
  const dome = new THREE.Mesh(domeG, jbWood); dome.position.set(0, 0.25, 0); jb.add(dome);
  const jbGlowMat = new THREE.MeshBasicMaterial({ color: 0xffc866 });
  const jbFace = canvasTex(32, 32, (g, w, h) => {
    g.fillStyle = "#3a1c0c"; g.fillRect(0, 0, w, h);
    const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#ffd37a"); gr.addColorStop(1, "#ff8a3a");
    g.fillStyle = gr; g.fillRect(4, 3, 24, 13);
    g.fillStyle = "#3a1c0c"; g.font = "bold 8px monospace"; g.textAlign = "center"; g.fillText("♪ ♫ ♪", 16, 13);
    g.fillStyle = "#c9a45a"; for (let i = 0; i < 4; i++) g.fillRect(5, 20 + i * 3, 22, 1);
  });
  const jbFaceMat = new THREE.MeshBasicMaterial({ map: jbFace });
  box(0.26, 0.26, 0.01, jbFaceMat, 0, 0.17, 0.103, jb);                                   // lit front panel
  box(0.04, 0.04, 0.02, 0xd9b45a, -0.1, 0.05, 0.1, jb); box(0.04, 0.04, 0.02, 0xd9b45a, 0.1, 0.05, 0.1, jb); // knobs
  const jbLight = new THREE.PointLight(0xffb450, 0, 1.2, 1.6); jbLight.position.set(0, 0.2, 0.25); jb.add(jbLight);
  const jbMeshes = [];
  jb.traverse(o => { if (o.isMesh) { o.userData.pick = { kind: "jukebox" }; jbMeshes.push(o); } });
  scene.userData.jukebox = { group: jb, meshes: jbMeshes, wood: jbWood, face: jbFaceMat, light: jbLight };

  // framed pictures
  const painting = (a, b) => canvasTex(24, 16, (g, w, h) => { g.fillStyle = a; g.fillRect(0, 0, w, h); g.fillStyle = b; g.fillRect(0, h * 0.62, w, h); g.fillStyle = "#2a3a20";
    for (let i = 0; i < 4; i++) { g.beginPath(); g.moveTo(i * 6 + 2, h * 0.65); g.lineTo(i * 6 + 5, h * 0.3); g.lineTo(i * 6 + 8, h * 0.65); g.fill(); } g.fillStyle = "#3a5a7a"; g.fillRect(2, h * 0.8, w - 6, 2); });
  [[1.35, 1.95, 0.95, 0.68, "#7a8a9a", "#7a7a4a"], [2.55, 1.85, 0.6, 0.48, "#9a8a6a", "#6a6a3a"]].forEach(([x, y, w, h, a, b]) => {
    box(w, h, 0.05, 0x5a3218, x, y, -1.88, scene);
    box(w - 0.14, h - 0.14, 0.02, mat(0xffffff, { map: painting(a, b) }), x, y, -1.85, scene);
  });

  // side table + lamp (warm light)
  box(0.55, 0.62, 0.45, 0x5a3720, 2.75, 0.31, -1.2, scene);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.1, 0.35, 6), mat(0x3a2a1a)); base.position.set(2.75, 0.8, -1.2); scene.add(base);
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.26, 0.28, 6, 1, true),
    new THREE.MeshBasicMaterial({ color: 0xffb04a, side: THREE.DoubleSide })); shade.position.set(2.75, 1.1, -1.2); scene.add(shade);
  const lamp = new THREE.PointLight(0xffa24a, 6, 0, 1.6); lamp.position.set(2.75, 1.05, -1.1); scene.add(lamp);

  // desk
  box(1.8, 0.06, 0.9, 0x7a4a26, 0, 0.74, -0.08, scene);
  [[-0.84, -0.48], [0.84, -0.48], [-0.84, 0.32], [0.84, 0.32]].forEach(([x, z]) => box(0.06, 0.72, 0.06, 0x5a3418, x, 0.36, z, scene));
  box(0.42, 0.5, 0.8, 0x6a3f20, 0.6, 0.45, -0.08, scene);                                   // drawer block

  // CRT monitor
  const mon = new THREE.Group(); mon.position.set(-0.05, 0.77, -0.22); mon.rotation.y = -0.22; scene.add(mon);
  const beige = 0xd9cdaa;
  box(0.3, 0.03, 0.26, beige, 0, 0.015, 0, mon); box(0.14, 0.06, 0.12, beige, 0, 0.05, 0, mon);
  box(0.6, 0.48, 0.46, beige, 0, 0.32, 0, mon);
  box(0.44, 0.36, 0.26, 0xcbbf9c, 0, 0.32, -0.34, mon);
  box(0.6, 0.48, 0.02, 0xcabd98, 0, 0.32, 0.235, mon);                                       // bezel face
  const term = canvasTex(160, 120, (g, w, h) => { g.fillStyle = "#0d1a0d"; g.fillRect(0, 0, w, h); });
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.47, 0.35), new THREE.MeshBasicMaterial({ map: term }));
  screen.position.set(0, 0.33, 0.247); mon.add(screen);
  box(0.03, 0.02, 0.01, new THREE.MeshBasicMaterial({ color: 0x6fe36f }), 0.24, 0.12, 0.247, mon);

  // keyboard, mouse, tower, mug, papers
  const kb = new THREE.Group(); kb.position.set(-0.02, 0.775, 0.2); kb.rotation.y = -0.22; scene.add(kb);
  const keys = canvasTex(48, 16, (g, w, h) => { g.fillStyle = "#cfc3a2"; g.fillRect(0, 0, w, h); g.fillStyle = "#e9dfc4";
    for (let r = 0; r < 4; r++) for (let c = 0; c < 15; c++) g.fillRect(1 + c * 3.1 + (r % 2), 1 + r * 3.8, 2, 2.6); });
  box(0.48, 0.03, 0.16, mat(0xffffff, { map: keys }), 0, 0, 0, kb);
  box(0.32, 0.005, 0.26, 0x2a2e3a, 0.38, 0.775, 0.22, scene);
  box(0.07, 0.035, 0.11, beige, 0.38, 0.795, 0.22, scene);
  box(0.21, 0.48, 0.46, beige, 0.62, 1.01, -0.2, scene);
  box(0.12, 0.02, 0.01, 0x8a8068, 0.62, 1.15, 0.031, scene);
  box(0.025, 0.025, 0.01, new THREE.MeshBasicMaterial({ color: 0x7cff5a }), 0.66, 0.86, 0.031, scene);
  const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, 0.11, 7), mat(0xe6e0d2)); mug.position.set(-0.62, 0.83, 0.12); scene.add(mug);
  box(0.24, 0.004, 0.3, 0xf2eee2, 0.55, 0.774, 0.28, scene).rotation.y = 0.3;
  box(0.26, 0.06, 0.2, 0x7d2a22, -0.62, 0.8, -0.3, scene); box(0.24, 0.05, 0.19, 0x2d4a3a, -0.62, 0.855, -0.3, scene);

  // chair at the keyboard
  const pcChair = makeChair(scene, SEAT, Math.PI);
  const seatMeshes = [];
  pcChair.traverse(o => { if (o.isMesh) { o.userData.pick = { kind: "seat" }; seatMeshes.push(o); } });
  scene.userData.seatMeshes = seatMeshes;

  return { screen, term, mon };
}

// ---------------------------------------------------------------- characters
// Each person is ONE continuous skinned mesh (torso -> neck -> head, with arms
// and legs growing out of it), smooth shaded, driven by a small skeleton.
// The front of the head is flattened so the low-res face photo projects cleanly.

// bone indices
const B = { root: 0, spine: 1, head: 2, shL: 3, elL: 4, shR: 5, elR: 6, thL: 7, knL: 8, thR: 9, knR: 10 };

function disposeObject(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set(), skeletons = new Set();
  root.traverse(o => {
    if (o.geometry) geometries.add(o.geometry);
    if (o.skeleton) skeletons.add(o.skeleton);
    for (const m of (Array.isArray(o.material) ? o.material : o.material ? [o.material] : [])) {
      materials.add(m);
      for (const value of Object.values(m)) if (value && value.isTexture) textures.add(value);
    }
  });
  for (const s of skeletons) s.dispose();
  for (const t of textures) t.dispose();
  for (const g of geometries) g.dispose();
  for (const m of materials) m.dispose();
}

function buildChar(color, face, pants) {
  let disposed = false;
  const C = (h) => new THREE.Color(h);
  const SWEATER = C(color), SKIN = C(face ? face.skin : "#d8a890"), HAIR = C(face ? face.hair : "#3a2a20"),
        PANTS = C(pants), SHOE = C(0x231a14);
  const pos = [], col = [], uv = [], si = [], sw = [], idxBody = [], idxFace = [];
  const v3 = new THREE.Vector3();
  let seed = (color * 9301 + 49297) % 233280;
  const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;

  function vert(p, c, w, jitter = 0) {       // w: [[bone, weight], ...]
    pos.push(p.x, p.y, p.z);
    const j = 1 + (rnd() - 0.5) * jitter;
    col.push(c.r * j, c.g * j, c.b * j);
    uv.push(0, 0);
    const ws = [...w, [0, 0], [0, 0], [0, 0]].slice(0, 4);
    si.push(...ws.map(x => x[0])); sw.push(...ws.map(x => x[1]));
    return pos.length / 3 - 1;
  }
  // stitch consecutive rings (arrays of vertex indices) into quads
  function stitch(rings, faceTest) {
    for (let i = 0; i < rings.length - 1; i++) {
      const A = rings[i], Bn = rings[i + 1], n = A.length;
      for (let k = 0; k < n; k++) {
        const a = A[k], b = A[(k + 1) % n], c = Bn[(k + 1) % n], d = Bn[k];
        const target = faceTest && faceTest(a, b, c, d) ? idxFace : idxBody;
        target.push(a, c, b, a, d, c);
      }
    }
  }
  function capRing(ring, center, flip) {
    for (let k = 0; k < ring.length; k++) {
      const a = ring[k], b = ring[(k + 1) % ring.length];
      flip ? idxBody.push(center, a, b) : idxBody.push(center, b, a);
    }
  }

  // ---- torso + neck + head: one tube, rings from the crotch up to the crown
  const SIDES = 8;
  const FACE_Y0 = 1.445, FACE_Y1 = 1.76, FACE_W = 0.13;
  const T = [ // y, rx, rz, zOffset, color(angle, z), weights, flatten front (head)?
    [0.74, 0.158, 0.108, 0, () => PANTS, [[B.root, 1]]],
    [0.82, 0.178, 0.122, 0.004, () => PANTS, [[B.root, 1]]],
    [0.875, 0.172, 0.118, 0.006, () => SWEATER, [[B.root, 0.5], [B.spine, 0.5]]],
    [0.97, 0.152, 0.104, 0.008, () => SWEATER, [[B.spine, 1]]],
    [1.15, 0.155, 0.104, 0.006, () => SWEATER, [[B.spine, 1]]],
    [1.29, 0.156, 0.094, 0, () => SWEATER, [[B.spine, 1]]],
    [1.355, 0.122, 0.077, 0, () => SWEATER, [[B.spine, 1]]],
    [1.395, 0.066, 0.056, 0, () => SKIN, [[B.spine, 0.7], [B.head, 0.3]]],      // short neck
    [1.425, 0.052, 0.05, 0.004, () => SKIN, [[B.spine, 0.3], [B.head, 0.7]]],
    // head (front flattened into the face plane)
    [1.455, 0.064, 0.062, 0.02, () => SKIN, [[B.head, 1]], true],
    [1.51, 0.108, 0.1, 0.01, (a, z) => z < -0.05 ? HAIR : SKIN, [[B.head, 1]], true],
    [1.585, 0.124, 0.112, 0, (a, z) => z < -0.01 ? HAIR : SKIN, [[B.head, 1]], true],
    [1.665, 0.12, 0.11, -0.004, (a, z) => z < 0.04 ? HAIR : SKIN, [[B.head, 1]], true],
    [1.73, 0.088, 0.088, -0.01, () => HAIR, [[B.head, 1]], true],
    [1.758, 0.04, 0.045, -0.015, () => HAIR, [[B.head, 1]]],
  ];
  const FRONT = 0.082;                          // flat face plane (z) for head rings
  const isFace = new Set();
  const torsoRings = T.map(([y, rx, rz, zo, cf, w, flat]) => {
    const ring = [];
    for (let k = 0; k < SIDES; k++) {
      const a = k / SIDES * Math.PI * 2 + Math.PI / SIDES;
      let x = Math.cos(a) * rx, z = Math.sin(a) * rz + zo;
      if (flat && z > FRONT) z = FRONT;           // flatten the face
      v3.set(x, y, z);
      const id = vert(v3, cf(a, z), w, cf(a, z) === SWEATER ? 0.12 : 0.04);
      if (flat) {
        uv[id * 2] = 0.5 + x / (2 * FACE_W); uv[id * 2 + 1] = Math.min(1, Math.max(0, (y - FACE_Y0) / (FACE_Y1 - FACE_Y0)));
        if (z > 0.03) isFace.add(id);
      }
      ring.push(id);
    }
    return ring;
  });
  // face quads = all four corners on the flat front plane
  stitch(torsoRings, (a, b, c, d) => [a, b, c, d].filter(i => isFace.has(i)).length >= 3);
  const bottom = vert(v3.set(0, 0.73, 0), PANTS, [[B.root, 1]]);
  capRing(torsoRings[0], bottom, true);
  const top = vert(v3.set(0, 1.765, -0.015), HAIR, [[B.head, 1]]);
  capRing(torsoRings[torsoRings.length - 1], top, false);
  // fill the face plane quads that touch the edge only partly (keep photo complete)
  // (they stay skin-coloured, which reads as the edge of the face)

  // ---- tubes along a path (arms, legs, long hair)
  function tube(points, ref, sides = 8) {
    const rings = [];
    for (let i = 0; i < points.length; i++) {
      const p = points[i].p;
      const prev = points[Math.max(0, i - 1)].p, next = points[Math.min(points.length - 1, i + 1)].p;
      const Tg = new THREE.Vector3().subVectors(next, prev).normalize();
      const Bn = new THREE.Vector3().crossVectors(Tg, ref).normalize();
      const N = new THREE.Vector3().crossVectors(Bn, Tg).normalize();
      const ring = [];
      for (let k = 0; k < sides; k++) {
        const a = k / sides * Math.PI * 2;
        const rr = points[i].r, rz = points[i].rz ?? rr;
        v3.copy(p).addScaledVector(N, Math.cos(a) * rz).addScaledVector(Bn, Math.sin(a) * rr);
        ring.push(vert(v3, points[i].c, points[i].w, points[i].c === SWEATER ? 0.12 : 0.04));
      }
      rings.push(ring);
    }
    stitch(rings);
    const first = points[0], last = points[points.length - 1];
    capRing(rings[0], vert(first.p.clone(), first.c, first.w), true);
    capRing(rings[rings.length - 1], vert(last.p.clone(), last.c, last.w), false);
  }
  const P = (x, y, z) => new THREE.Vector3(x, y, z);
  for (const sx of [-1, 1]) {
    const sh = sx < 0 ? B.shL : B.shR, el = sx < 0 ? B.elL : B.elR;
    tube([   // arm: starts inside the chest, arches over the shoulder, down to the hand
      { p: P(sx * 0.08, 1.285, 0), r: 0.055, c: SWEATER, w: [[B.spine, 1]] },
      { p: P(sx * 0.15, 1.3, 0), r: 0.057, c: SWEATER, w: [[B.spine, 0.6], [sh, 0.4]] },
      { p: P(sx * 0.195, 1.24, 0), r: 0.053, c: SWEATER, w: [[sh, 1]] },
      { p: P(sx * 0.205, 1.05, 0), r: 0.045, c: SWEATER, w: [[sh, 0.5], [el, 0.5]] },
      { p: P(sx * 0.205, 0.815, 0), r: 0.035, c: SWEATER, w: [[el, 1]] },
      { p: P(sx * 0.207, 0.75, 0.005), r: 0.043, rz: 0.024, c: SKIN, w: [[el, 1]] },
      { p: P(sx * 0.207, 0.69, 0.008), r: 0.016, rz: 0.01, c: SKIN, w: [[el, 1]] },
    ], new THREE.Vector3(0, 0, 1), 6);
    const th = sx < 0 ? B.thL : B.thR, kn = sx < 0 ? B.knL : B.knR;
    tube([   // leg: starts inside the pelvis, down to the foot
      { p: P(sx * 0.085, 0.9, 0), r: 0.095, c: PANTS, w: [[B.root, 1]] },
      { p: P(sx * 0.09, 0.78, 0), r: 0.102, c: PANTS, w: [[B.root, 0.3], [th, 0.7]] },
      { p: P(sx * 0.09, 0.4, 0), r: 0.071, c: PANTS, w: [[th, 0.5], [kn, 0.5]] },
      { p: P(sx * 0.09, 0.28, -0.006), r: 0.069, c: PANTS, w: [[kn, 1]] },
      { p: P(sx * 0.09, 0.08, 0), r: 0.049, c: PANTS, w: [[kn, 1]] },
      { p: P(sx * 0.09, 0.04, 0.05), r: 0.056, rz: 0.038, c: SHOE, w: [[kn, 1]] },
      { p: P(sx * 0.09, 0.03, 0.17), r: 0.032, rz: 0.021, c: SHOE, w: [[kn, 1]] },
    ], new THREE.Vector3(1, 0, 0), 6);
  }
  if (face && face.long)   // long hair falling down the back, part of the same mesh
    tube([
      { p: P(0, 1.73, -0.06), r: 0.12, rz: 0.06, c: HAIR, w: [[B.head, 1]] },
      { p: P(0, 1.58, -0.1), r: 0.135, rz: 0.06, c: HAIR, w: [[B.head, 1]] },
      { p: P(0, 1.42, -0.1), r: 0.125, rz: 0.045, c: HAIR, w: [[B.head, 0.6], [B.spine, 0.4]] },
      { p: P(0, 1.32, -0.085), r: 0.1, rz: 0.03, c: HAIR, w: [[B.head, 0.3], [B.spine, 0.7]] },
    ], new THREE.Vector3(1, 0, 0), 6);

  // ---- geometry
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(si, 4));
  g.setAttribute("skinWeight", new THREE.Float32BufferAttribute(sw, 4));
  g.setIndex([...idxBody, ...idxFace]);
  g.addGroup(0, idxBody.length, 0);
  g.addGroup(idxBody.length, idxFace.length, 1);
  g.computeVertexNormals();

  const bodyMat = new THREE.MeshLambertMaterial({ vertexColors: true });
  const faceMat = new THREE.MeshLambertMaterial({ color: SKIN, emissive: 0x30241a });
  if (face) texLoader.load(new URL("./faces/" + face.file, import.meta.url).href, t => {
    if (disposed) { t.dispose(); return; }
    t.magFilter = t.minFilter = THREE.NearestFilter; t.colorSpace = THREE.SRGBColorSpace;
    faceMat.map = t; faceMat.color.set(0xffffff); faceMat.needsUpdate = true;
  });

  // ---- skeleton (bind pose = standing, matching the vertices above)
  const bone = (x, y, z, parent) => { const b = new THREE.Bone(); b.position.set(x, y, z); if (parent) parent.add(b); return b; };
  const root = bone(0, 0, 0);
  const spine = bone(0, 0.8, 0, root);
  const head = bone(0, 0.59, 0, spine);
  const shL = bone(-0.195, 0.52, 0, spine), elL = bone(0, -0.27, 0, shL);
  const shR = bone(0.195, 0.52, 0, spine), elR = bone(0, -0.27, 0, shR);
  const thL = bone(-0.09, 0.8, 0, root), knL = bone(0, -0.4, 0, thL);
  const thR = bone(0.09, 0.8, 0, root), knR = bone(0, -0.4, 0, thR);
  const bones = [root, spine, head, shL, elL, shR, elR, thL, knL, thR, knR];
  const mesh = new THREE.SkinnedMesh(g, [bodyMat, faceMat]);
  mesh.add(root);
  mesh.bind(new THREE.Skeleton(bones));
  mesh.frustumCulled = false;
  const group = new THREE.Group(); group.add(mesh);
  // hover outline: inverted hull sharing the skeleton, pushed out along the skinned normals
  const olMat = new THREE.MeshBasicMaterial({ color: 0xcfc2a6, side: THREE.DoubleSide,
    stencilWrite: true, stencilRef: 1, stencilFunc: THREE.NotEqualStencilFunc })   // only outside the body silhouette;
  // push along the radial direction away from each vertex's main bone segment (robust to mixed face winding)
  root.updateMatrixWorld(true);
  const segs = bones.map(bn => {
    const p0 = bn.getWorldPosition(new THREE.Vector3()), kid = bn.children.find(k => k.isBone);
    const p1 = kid ? kid.getWorldPosition(new THREE.Vector3()) : bn === head ? p0.clone().add(new THREE.Vector3(0, 0.12, 0))
      : bn.parent && bn.parent.isBone && bn !== root ? p0.clone().add(bn.position) : p0.clone();
    return [p0, p1];
  });
  const od = new Float32Array(pos.length), line = new THREE.Line3(), cp = new THREE.Vector3();
  for (let i = 0; i < pos.length / 3; i++) {
    let bi = 0, bw = -1; for (let k = 0; k < 4; k++) if (sw[i * 4 + k] > bw) { bw = sw[i * 4 + k]; bi = si[i * 4 + k]; }
    v3.fromArray(pos, i * 3); line.set(segs[bi][0], segs[bi][1]); line.closestPointToPoint(v3, true, cp);
    cp.subVectors(v3, cp); if (cp.lengthSq() < 1e-8) cp.set(0, 1, 0); cp.normalize().toArray(od, i * 3);
  }
  g.setAttribute("outdir", new THREE.BufferAttribute(od, 3));
  olMat.onBeforeCompile = sh => {
    sh.vertexShader = "attribute vec3 outdir;\n" + sh.vertexShader.replace("#include <skinning_vertex>",
      "#include <skinning_vertex>\n  transformed += normalize((skinMatrix * vec4(outdir, 0.0)).xyz) * 0.014;");
  };
  const outline = new THREE.SkinnedMesh(g, olMat);
  outline.bind(mesh.skeleton, mesh.bindMatrix.clone());
  outline.frustumCulled = false; outline.visible = false; outline.renderOrder = 1; group.add(outline);
  for (const m of [bodyMat, faceMat]) Object.assign(m, { stencilWrite: true, stencilRef: 1, stencilZPass: THREE.ReplaceStencilOp });
  // invisible, generous pick volume (raycasting a skinned mesh is slow and fiddly)
  const hit = new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 1.7, 8), new THREE.MeshBasicMaterial());
  hit.position.y = 0.85; hit.visible = false; group.add(hit);
  // A captain's cap identifies agents with supervisor permissions and follows head motion.
  const leaderHat = new THREE.Group(); head.add(leaderHat); leaderHat.visible = false;
  box(0.34, 0.025, 0.3, 0x172337, 0, 0.375, 0.025, leaderHat);
  box(0.26, 0.105, 0.23, 0x263f63, 0, 0.435, -0.005, leaderHat);
  box(0.265, 0.025, 0.235, 0xe6b84d, 0, 0.393, -0.005, leaderHat);
  box(0.055, 0.055, 0.012, 0xffd86b, 0, 0.438, 0.116, leaderHat);
  return { root: group, outline, hit, bodyMat, upper: spine, head, leaderHat, armL: shL, armR: shR, elbowL: elL, elbowR: elR, legL: thL, legR: thR, kneeL: knL, kneeR: knR,
    dispose() { if (!disposed) { disposed = true; disposeObject(group); } } };
}

// ---------------------------------------------------------------- homography (sharp DOM onto the CRT)
function adj(m) { return [m[4] * m[8] - m[5] * m[7], m[2] * m[7] - m[1] * m[8], m[1] * m[5] - m[2] * m[4], m[5] * m[6] - m[3] * m[8], m[0] * m[8] - m[2] * m[6], m[2] * m[3] - m[0] * m[5], m[3] * m[7] - m[4] * m[6], m[1] * m[6] - m[0] * m[7], m[0] * m[4] - m[1] * m[3]]; }
function mulmm(a, b) { const c = Array(9); for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) { let s = 0; for (let k = 0; k < 3; k++) s += a[3 * i + k] * b[3 * k + j]; c[3 * i + j] = s; } return c; }
function mulmv(m, v) { return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]; }
function basis(p) { const m = [p[0], p[2], p[4], p[1], p[3], p[5], 1, 1, 1]; const v = mulmv(adj(m), [p[6], p[7], 1]); return mulmm(m, [v[0], 0, 0, 0, v[1], 0, 0, 0, v[2]]); }
function quadTransform(w, h, dst) {
  const t = mulmm(basis(dst), adj(basis([0, 0, w, 0, 0, h, w, h])));
  for (let i = 0; i < 9; i++) t[i] /= t[8];
  return `matrix3d(${[t[0], t[3], 0, t[6], t[1], t[4], 0, t[7], 0, 0, 1, 0, t[2], t[5], 0, t[8]].join(",")})`;
}

// ---------------------------------------------------------------- public API
// ---------------- jukebox: tiny WebAudio lobby-music synth (no assets)
function createJukebox(saved = {}, onChange = () => {}) {
  let ctx = null, master = null, timer = null, nextT = 0;
  let step = Number.isSafeInteger(saved.step) && saved.step >= 0 ? saved.step : 0;
  let playing = saved.playing === true;
  // Restored audio may need the first user gesture under browser autoplay rules.
  function resume() {
    if (!playing) return;
    try {
      if (!ctx) { ctx = new (window.AudioContext || window.webkitAudioContext)(); master = ctx.createGain(); master.gain.value = 0; master.connect(ctx.destination); }
      ctx.resume().then(() => {
        if (!playing || timer !== null || ctx.state !== "running") return;
        master.gain.cancelScheduledValues(ctx.currentTime);
        master.gain.setTargetAtTime(volume(), ctx.currentTime, 0.05);
        nextT = ctx.currentTime + 0.05; schedule(); timer = setInterval(schedule, 100);
      }).catch(() => {});
    } catch (e) { /* Audio unavailable; retain the user's on/off preference. */ }
  }
  for (const event of ["pointerdown", "keydown"]) document.addEventListener(event, resume, { passive: true });
  function volume() {
    try {
      const v = parseFloat(localStorage.getItem("mr_musicvol"));
      return v >= 0 && v <= 1 ? v : 0.5;
    } catch (e) { return 0.5; }
  }
  window.addEventListener("storage", e => {
    if ((e.key === "mr_musicvol" || e.key === null) && master && playing) {
      master.gain.cancelScheduledValues(ctx.currentTime);
      master.gain.setTargetAtTime(volume(), ctx.currentTime, 0.05);
    }
  });
  const BPM = 84, B = 60 / BPM;
  const f = m => 440 * Math.pow(2, (m - 69) / 12);
  // Cmaj7 - Am7 - Dm7 - G7, one bar each (4 beats)
  const CH = [[48, 55, 59, 64], [45, 52, 59, 64], [50, 57, 60, 65], [43, 53, 59, 62]];
  const PENT = [72, 74, 76, 79, 81, 84];
  function tone(m, t, dur, vol, type) {
    const o = ctx.createOscillator(), g = ctx.createGain(), lp = ctx.createBiquadFilter();
    o.type = type; o.frequency.value = f(m); lp.type = "lowpass"; lp.frequency.value = 1800;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    o.connect(lp); lp.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.05);
  }
  function schedule() {
    while (nextT < ctx.currentTime + 0.4) {
      const bar = Math.floor(step / 8) % CH.length, e = step % 8, ch = CH[bar];
      if (e % 2 === 0) tone(ch[(e / 2) % 4] - (e === 0 ? 12 : 0), nextT, B * 1.6, 0.11, "triangle");     // arpeggiated electric-piano comp
      if (e === 0) ch.slice(1).forEach(m => tone(m, nextT, B * 3.6, 0.04, "sine"));                       // soft pad
      if (Math.random() < 0.38) tone(PENT[Math.floor(Math.random() * PENT.length)], nextT, B * 0.9, 0.07, "sine"); // tinkly lead
      nextT += B / 2; step++;
    }
  }
  if (playing) resume();
  return {
    get playing() { return playing; },
    snapshot() { return { playing, step }; },
    toggle() {
      playing = !playing;
      if (playing) resume();
      else {
        clearInterval(timer); timer = null;
        if (master) master.gain.setTargetAtTime(0, ctx.currentTime, 0.15);
      }
      onChange();
    },
  };
}


export function createRoom({ wrap, canvas, labels, overlay, overlayW = 800, overlayH = 600, onPick = () => {}, onFocusChange = () => {} }) {
  // One snapshot per room in this browser; never restore server-owned status.
  const stateKey = "mr_roomstate_v1:" + location.pathname.replace(/\/+$/, "");
  let saved = {};
  try {
    const value = JSON.parse(localStorage.getItem(stateKey));
    if (value && value.version === 1) saved = value;
  } catch (e) { /* Storage may be unavailable or contain an older/corrupt value. */ }
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, stencil: true });
  renderer.setPixelRatio(1);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a120c);
  scene.fog = new THREE.Fog(0x1a120c, 6, 11);
  scene.add(new THREE.HemisphereLight(0xffdcae, 0x3a2716, 1.25));
  const moon = new THREE.DirectionalLight(0x8fa6ff, 0.35); moon.position.set(-3, 3, 1); scene.add(moon);
  const { screen, term, mon } = buildRoom(scene);
  overlay.style.pointerEvents = "none";

  const camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.05, 30);
  const ROOM_POS = new THREE.Vector3(-1.3, 2.25, 4.3), ROOM_LOOK = new THREE.Vector3(0.1, 0.92, -0.4);
  const sc = new THREE.Vector3(); screen.getWorldPosition(sc);
  const sn = new THREE.Vector3(0, 0, 1).applyQuaternion(screen.getWorldQuaternion(new THREE.Quaternion()));
  const FOCUS_POS = new THREE.Vector3(), FOCUS_LOOK = sc.clone();
  const SW = screen.geometry.parameters.width, SH = screen.geometry.parameters.height;
  function updateFocusPose() {
    const tanH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)), fill = 0.9;
    const d = Math.max(SH / fill / (2 * tanH), SW / fill / (2 * tanH * camera.aspect));
    FOCUS_POS.copy(sc).addScaledVector(sn, d);
  }
  let focusK = 0, focus = false;
  const camLook = new THREE.Vector3();

  const chars = new Map();       // name -> state
  let seatOwner = typeof saved.seatOwner === "string" ? saved.seatOwner : null;
  const typingAnyone = () => [...chars.values()].some(c => c.working && c.arrived);

  function resize() {
    const r = wrap.getBoundingClientRect();
    renderer.setSize(Math.max(1, Math.round(r.width / PIX)), Math.max(1, Math.round(r.height / PIX)), false);
    canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
    camera.aspect = r.width / Math.max(1, r.height); camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(wrap); resize();

  function setAgents(list) {
    const names = new Set(list.map(a => a.name));
    for (const [name, c] of [...chars]) {          // someone left: take them and their chair out of the room
      if (names.has(name)) continue;
      scene.remove(c.rig.root); if (c.chair) scene.remove(c.chair); c.el.remove();
      c.rig.dispose(); if (c.chair) disposeObject(c.chair);
      if (seatOwner === name) seatOwner = null;
      leanSpots.delete(name);
      if (tagHover === name) tagHover = null;
      chars.delete(name);
    }
    list.forEach((a, i) => {
      let c = chars.get(a.name);
      if (!c) {
        const taken = new Set([...chars.values()].map(x => x.idx));
        const sv = saved.agents && Object.hasOwn(saved.agents, a.name) ? saved.agents[a.name].idx : null;
        i = Number.isInteger(sv) && !taken.has(sv) ? sv : (() => { let k = 0; while (taken.has(k)) k++; return k; })();
        const fid = a.face || FACE_ORDER[[...a.name].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7) % FACE_ORDER.length];   // server sends a fixed face; name hash only as fallback
        const rig = buildChar(new THREE.Color(a.color).getHex(), FACES[(fid - 1) % Math.max(1, FACES.length)] || null, PANTS[i % PANTS.length]);
        scene.add(rig.root);
        const home = homeFor(i);
        rig.root.position.copy(home);
        const chairYaw = lerpAngle(Math.atan2(-0.2 - home.x, -0.2 - home.z), Math.atan2(ROOM_POS.x - home.x, ROOM_POS.z - home.z), 0.55);
        const chair = makeChair(scene, home, chairYaw);
        const el = document.createElement("div"); el.className = "lbl";
        el.innerHTML = `<div class="bubble"></div><div class="tag"><i style="background:${a.color}"></i><b></b><span></span></div>`;
        labels.appendChild(el);
        rig.hit.userData.pick = { kind: "agent", name: a.name };
        const tag = el.querySelector(".tag"); tag.style.pointerEvents = "auto"; tag.style.cursor = "pointer";
        tag.addEventListener("mouseenter", () => { tagHover = a.name; });
        tag.addEventListener("mouseleave", () => { if (tagHover === a.name) tagHover = null; });
        tag.addEventListener("click", e => { e.stopPropagation(); if (!focus) onPick({ kind: "agent", name: a.name, x: e.clientX, y: e.clientY }); });
        c = { name: a.name, rig, chair, home, chairYaw, pos: rig.root.position, yaw: Math.PI, el, idx: i, phase: Math.random() * 6,
              sit: 0, lean: 0, armX: 0, legX: 0, walk: 0, saying: null, sayUntil: 0, arrived: false, lastActive: performance.now(), doze: 0 };
        const prior = saved.agents && Object.hasOwn(saved.agents, a.name) ? saved.agents[a.name] : null;
        if (prior && Array.isArray(prior.pos) && prior.pos.length === 3 && prior.pos.every(Number.isFinite)
            && Math.abs(prior.pos[0]) < 5 && Math.abs(prior.pos[2]) < 5) {
          c.pos.fromArray(prior.pos);
          for (const key of ["yaw", "sit", "lean", "walk", "phase", "doze"])
            if (Number.isFinite(prior[key])) c[key] = prior[key];
          c.atComputer = prior.atComputer === true;
          c.arrived = prior.arrived === true;
          if (Number.isFinite(prior.inactiveMs)) c.lastActive -= Math.max(0, prior.inactiveMs);
          c.rig.root.rotation.y = c.yaw;
        }
        chars.set(a.name, c);
      }
      c.status = a.status; c.activity = a.activity || ""; c.color = a.color;
      c.rig.leaderHat.visible = a.supervisor === true;
      c.busy = a.status === "thinking" || a.status === "working";
      c.working = a.status === "working";
      // Stay at the PC through pauses between tools, until this turn ends.
      c.atComputer = c.working || (!!c.atComputer && (c.busy || a.status === "waiting"));
      c.el.querySelector("b").textContent = a.person || a.name;
      c.el.querySelector("span").textContent = a.status === "offline" ? "offline" : a.status === "sleeping" ? "sleeping" : "";
    });
    if (!chars.get(seatOwner)?.atComputer) seatOwner = null;
  }

  function say(name, text, ms) { const c = chars.get(name); if (!c) return; c.saying = text; c.sayUntil = ms == null ? Infinity : performance.now() + ms; }
  function quiet(name) { const c = chars.get(name); if (c) { c.saying = null; c.sayUntil = 0; } }

  // ---------------- terminal texture on the CRT (visible when nothing is shared)
  const tg = term.userData.canvas.getContext("2d");
  const lines = [];
  let lastTerm = 0, screenActive = false;
  function drawTerm(t) {
    tg.fillStyle = "#0b170b"; tg.fillRect(0, 0, 160, 120);
    tg.fillStyle = "#1c3a1c"; tg.fillRect(0, 0, 160, 8);
    tg.fillStyle = "#7fe07a"; tg.fillRect(3, 2, 30, 4);
    const busy = typingAnyone();
    if (busy && t - lastTerm > 90) { lastTerm = t; lines.push(4 + Math.floor(Math.random() * 18)); if (lines.length > 13) lines.shift(); }
    if (!busy && !lines.length) for (let i = 0; i < 4; i++) lines.push(4 + i * 3);
    lines.forEach((n, i) => { tg.fillStyle = i % 4 === 0 ? "#b6f5a8" : "#6fd36a"; tg.fillRect(6, 13 + i * 8, 3, 3);
      for (let k = 0; k < n; k++) if ((k * 7 + i) % 5) tg.fillRect(12 + k * 6, 13 + i * 8, 5, 3); });
    if (Math.floor(t / 450) % 2) { tg.fillStyle = "#b6f5a8"; tg.fillRect(12, 13 + Math.min(lines.length, 13) * 8, 5, 4); }
    term.needsUpdate = true;
  }

  // ---------------- per-frame character logic
  const camPos = new THREE.Vector3(), tmp = new THREE.Vector3();
  const leanSpots = new Map(Array.isArray(saved.leanSpots)
    ? saved.leanSpots.filter(v => Array.isArray(v) && typeof v[0] === "string" && Number.isInteger(v[1]) && v[1] >= -1 && v[1] < LEAN.length) : []);
  function updateChar(c, dt, t) {
    const r = c.rig, now = performance.now();
    if (c.saying && now > c.sayUntil) c.saying = null;
    const sleeping = c.status === "sleeping";
    const speaking = !!c.saying && !sleeping, waiting = c.status === "waiting", offline = c.status === "offline";
    if (c.busy || speaking || waiting || c.nodUntil > now || !c.arrived) c.lastActive = now;
    const dozing = !sleeping && !offline && now - c.lastActive > DOZE_AFTER_MS;
    const ramp = Math.min(1, Math.max(0, (now - c.lastActive - DOZE_AFTER_MS) / 5000));   // drift off over ~5 s
    c.doze = dozing ? Math.max(c.doze, ramp * ramp * (3 - 2 * ramp)) : lerp(c.doze, 0, 1 - Math.pow(0.0005, dt));   // wake up fast
    const dz = c.doze;
    const jolt = (() => { const cy = (t + c.phase * 3) % 13; return cy < 0.6 ? Math.sin(cy / 0.6 * Math.PI) : 0; })();   // occasional head-jerk "I'm awake!"

    // where to be
    camera.getWorldPosition(camPos);
    const camYaw = Math.atan2(camPos.x - c.pos.x, camPos.z - c.pos.z);
    let target = c.home, pose = "stand", faceYaw = lerpAngle(Math.atan2(-0.2 - c.pos.x, -0.2 - c.pos.z), camYaw, 0.55);   // idle: half toward you
    if (c.atComputer) {
      if (!seatOwner || seatOwner === c.name) { seatOwner = c.name; target = SEAT; pose = "sit"; faceYaw = Math.PI; leanSpots.delete(c.name); }
      else {
        if (!leanSpots.has(c.name)) { const used = new Set(leanSpots.values()); leanSpots.set(c.name, LEAN.findIndex((_, i) => !used.has(i))); }
        const li = Math.max(0, leanSpots.get(c.name)); target = LEAN[li]; pose = "lean";
        faceYaw = Math.atan2(-0.05 - target.x, -0.15 - target.z);
      }
    } else {
      if (seatOwner === c.name) seatOwner = null;
      leanSpots.delete(c.name);
      pose = "sit"; faceYaw = c.chairYaw;          // idle: sit on own chair (still talks / raises a hand from there)
    }
    if ((speaking || waiting) && target !== c.home) faceYaw = camYaw;

    // walk there
    tmp.copy(target).sub(c.pos); tmp.y = 0;
    const dist = tmp.length();
    const moving = dist > 0.04;
    c.arrived = !moving;
    if (moving) {
      const step = Math.min(dist, 1.4 * dt);
      c.pos.addScaledVector(tmp.normalize(), step);
      faceYaw = Math.atan2(tmp.x, tmp.z); pose = "stand";
      c.walk += dt * 9;
    } else c.walk = 0;
    c.yaw = lerpAngle(c.yaw, faceYaw, 1 - Math.pow(0.0015, dt));
    r.root.rotation.y = c.yaw;

    // pose blending
    const k = 1 - Math.pow(0.002, dt);
    c.sit = lerp(c.sit, pose === "sit" ? 1 : 0, k);
    c.lean = lerp(c.lean, pose === "lean" ? 1 : pose === "sit" && c.working ? 0.25 : 0, k);
    r.root.position.y = -0.26 * c.sit;
    const swing = moving ? Math.sin(c.walk) * 0.6 : 0;
    r.legL.rotation.x = lerp(0, -1.5, c.sit) + swing; r.legR.rotation.x = lerp(0, -1.5, c.sit) - swing;
    r.kneeL.rotation.x = lerp(0, 1.5, c.sit) + (moving ? Math.max(0, -swing) * 0.9 : 0);
    r.kneeR.rotation.x = lerp(0, 1.5, c.sit) + (moving ? Math.max(0, swing) * 0.9 : 0);
    r.upper.rotation.x = 0.42 * c.lean + dz * (0.2 + Math.sin(t * 0.9 + c.phase) * 0.025) + (sleeping && !moving ? 0.25 + Math.sin(t * 1.4) * 0.02 : offline ? 0.15 : 0);
    r.upper.position.y = 0.8 + Math.sin(t * 1.6 + c.phase) * 0.006;

    // arms
    // arm targets: shoulder (a*), elbow (e*), sideways (z*)
    let aL = moving ? -swing * 0.7 : 0.03, aR = moving ? swing * 0.7 : 0.03, eL = -0.18, eR = -0.18, zL = 0.07, zR = -0.07;
    const typing = c.working && !moving && !speaking;
    if (typing) {
      const sit = pose === "sit";
      aL = (sit ? -0.45 : -0.75) + Math.sin(t * 17 + c.phase) * 0.05; aR = (sit ? -0.45 : -0.75) + Math.sin(t * 17 + c.phase + 2.2) * 0.05;
      eL = (sit ? -1.05 : -0.55) + Math.sin(t * 15 + c.phase) * 0.08; eR = (sit ? -1.05 : -0.55) + Math.sin(t * 15 + c.phase + 1.7) * 0.08;
      zL = 0.2; zR = -0.2;
    } else if (waiting && !moving) { aR = -2.85 + Math.sin(t * 6) * 0.08; eR = -0.35; zR = -0.22; }   // raised hand
    else if (speaking && !moving) {
      aL = -0.3 + Math.sin(t * 3.1) * 0.1; aR = -0.38 + Math.sin(t * 2.6 + 1) * 0.12;
      eL = -0.85 + Math.sin(t * 2.3) * 0.15; eR = -0.95 + Math.sin(t * 2.9 + 2) * 0.18; zL = 0.12; zR = -0.12;
    }
    if (dz > 0.01) {             // dozing: hands slump onto the lap
      aL = lerp(aL, -0.38, dz); aR = lerp(aR, -0.3, dz); eL = lerp(eL, -0.55, dz); eR = lerp(eR, -0.6, dz); zL = lerp(zL, 0.16, dz); zR = lerp(zR, -0.16, dz);
    }
    const kk = moving ? 1 : k;
    r.armL.rotation.x = lerp(r.armL.rotation.x, aL, kk); r.armR.rotation.x = lerp(r.armR.rotation.x, aR, kk);
    r.elbowL.rotation.x = lerp(r.elbowL.rotation.x, eL, kk); r.elbowR.rotation.x = lerp(r.elbowR.rotation.x, eR, kk);
    r.armL.rotation.z = lerp(r.armL.rotation.z, zL, k); r.armR.rotation.z = lerp(r.armR.rotation.z, zR, k);

    // head
    const nod = c.nodUntil > now ? Math.sin((1 - (c.nodUntil - now) / 700) * Math.PI * 2) * 0.28 : 0;
    r.head.rotation.x = nod + (sleeping && !moving ? 0.55 + Math.sin(t * 1.4) * 0.06 : offline ? 0.5 : typing ? 0.12 + Math.sin(t * 2 + c.phase) * 0.03 : speaking ? Math.sin(t * 7) * 0.05 : 0)
      + dz * (0.5 + Math.sin(t * 0.9 + c.phase) * 0.07 - jolt * 0.45);
    r.head.rotation.z = dz * (c.idx % 2 ? 0.2 : -0.2) * (1 - jolt * 0.6);

    // label + bubble
    tmp.set(0, 2.0 - 0.26 * c.sit, 0); r.root.localToWorld(tmp); tmp.project(camera);
    const W = wrap.clientWidth, H = wrap.clientHeight;
    const vis = tmp.z < 1;
    c.el.style.display = vis ? "" : "none";
    const lh = c.el.offsetHeight || 30, lw = (c.el.offsetWidth || 100) / 2;
    const lx = Math.min(W - lw - 6, Math.max(lw + 6, (tmp.x + 1) / 2 * W)), ly = Math.max(lh + 6, (1 - tmp.y) / 2 * H);
    c.el.style.transform = `translate(${lx.toFixed(1)}px, ${ly.toFixed(1)}px) translate(-50%, -100%)`;
    const bubble = c.el.firstChild;
    let text = "", cls = "bubble";
    if (sleeping) { text = "z Z Z · token limit · mention to retry"; cls += " sleep"; }
    else if (speaking) { text = c.saying.length > 150 ? c.saying.slice(0, 147) + "…" : c.saying; cls += " say"; }
    else if (waiting) { text = "! needs your approval"; cls += " wait"; }
    else if (dz > 0.6 && !c.busy) { text = "z"; cls += " doze"; }
    else if (c.busy) {
      const activity = (c.activity || (c.status === "thinking" ? "Reviewing request…" : "Working…")).replace(/\s+/g, " ").trim();
      const short = activity.split(" ").slice(0, 7).join(" ").slice(0, 64);
      text = "> " + short + (short.length < activity.length ? "…" : "");
      cls += " work";
    }
    bubble.title = c.busy && !speaking && !waiting ? "Activity from public messages and tool events" : "";
    if (bubble.textContent !== text) bubble.textContent = text;
    bubble.className = cls + (text ? "" : " hide");
    c.el.classList.toggle("off", offline);
    c.el.classList.toggle("sleeping", sleeping);
  }

  // ---------------- shared screen overlay
  function screenQuad() {
    const g = screen.geometry.parameters, W = wrap.clientWidth, H = wrap.clientHeight, pts = [];
    for (const [x, y] of [[-g.width / 2, g.height / 2], [g.width / 2, g.height / 2], [-g.width / 2, -g.height / 2], [g.width / 2, -g.height / 2]]) {
      tmp.set(x, y, 0.001); screen.localToWorld(tmp); tmp.project(camera);
      pts.push((tmp.x + 1) / 2 * W, (1 - tmp.y) / 2 * H);
    }
    return pts;
  }

  // ---------------- mouse interaction: hover highlight + click to pick
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const monMeshes = []; mon.traverse(o => { if (o.isMesh) { o.userData.pick = { kind: "monitor" }; monMeshes.push(o); } });
  const monMats = monMeshes.map(o => o.material).filter(m => m.emissive);
  const doorMeshes = scene.userData.doorMeshes || [], doorMat = scene.userData.doorMat;
  const jbx = scene.userData.jukebox, jukebox = createJukebox(saved.music || {}, saveState);
  let pointer = null, hovered = null, tagHover = null;
  canvas.addEventListener("pointermove", e => { pointer = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener("pointerleave", () => { pointer = null; });
  function pickAt(p) {
    if (!p || focus) return null;
    const r = canvas.getBoundingClientRect();
    ndc.set((p.x - r.left) / r.width * 2 - 1, -((p.y - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const targets = [...monMeshes, ...doorMeshes, ...jbx.meshes, ...(scene.userData.seatMeshes || [])]; for (const c of chars.values()) targets.push(c.rig.hit);
    const h = ray.intersectObjects(targets, false)[0];
    return h ? h.object.userData.pick : null;
  }
  const sameP = (a, b) => (a && a.kind) === (b && b.kind) && (a && a.name) === (b && b.name);
  function setHover(p) {
    if (sameP(p, hovered)) return;
    hovered = p;
    for (const c of chars.values()) {
      const on = !!p && p.kind === "agent" && p.name === c.name;
      c.rig.outline.visible = on; c.rig.bodyMat.emissive.setHex(on ? 0x14110c : 0x000000);
      c.el.classList.toggle("hover", on);
    }
    const monOn = !!p && p.kind === "monitor";
    for (const m of monMats) m.emissive.setHex(monOn ? 0x1e1a12 : 0x000000);
    if (doorMat) doorMat.emissive.setHex(p && p.kind === "door" ? 0x3a2a10 : 0x000000);
    jbx.wood.emissive.setHex(p && p.kind === "jukebox" ? 0x2a1a0a : 0x000000);
    (scene.userData.seatMeshes || []).forEach(m => m.material.emissive && m.material.emissive.setHex(p && p.kind === "seat" ? 0x2a1a0a : 0x000000));
    canvas.style.cursor = p ? "pointer" : focus ? "zoom-out" : "";
  }
  canvas.addEventListener("click", e => {
    if (focus) { setFocus(false); return; }                 // click beside the zoomed monitor: back to the room
    const p = pickAt({ x: e.clientX, y: e.clientY });
    if (p && p.kind === "monitor") { setFocus(true); return; }
    if (p && p.kind === "jukebox") { jukebox.toggle(); return; }
    onPick(p ? { ...p, x: e.clientX, y: e.clientY } : null);
  });
  function setFocus(v) {
    if (focus === v) return;
    focus = v; labels.classList.toggle("focus", v);
    overlay.style.pointerEvents = v ? "auto" : "none";     // in room view, clicks on the screen go to the 3D monitor
    if (v) setHover(null);
    canvas.style.cursor = v ? "zoom-out" : "";
    onFocusChange(v);
  }

  function saveState() {
    // Wait for the first roster so navigation during startup cannot erase agents.
    if (!chars.size) return;
    const agents = Object.fromEntries([...chars].map(([name, c]) => [name, {
      pos: c.pos.toArray(), yaw: c.yaw, sit: c.sit, lean: c.lean, walk: c.walk,
      idx: c.idx, phase: c.phase, doze: c.doze, inactiveMs: performance.now() - c.lastActive,
      atComputer: c.atComputer, arrived: c.arrived,
    }]));
    try { localStorage.setItem(stateKey, JSON.stringify({
      version: 1, agents, seatOwner, leanSpots: [...leanSpots], music: jukebox.snapshot(),
    })); } catch (e) { /* Full/disabled storage must not interrupt the room. */ }
  }
  window.addEventListener("pagehide", saveState);
  document.addEventListener("visibilitychange", () => { if (document.hidden) saveState(); });
  setInterval(() => { if (!document.hidden) saveState(); }, 1000);

  const frameInterval = 1000 / 30;  // keep animation cost independent of monitor refresh rate
  let last = performance.now(), lastFrame = last;
  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden || !wrap.clientWidth || !wrap.clientHeight) { last = lastFrame = now; return; }
    const elapsed = now - lastFrame;
    if (elapsed < frameInterval - 0.01) return;
    lastFrame += Math.floor((elapsed + 0.01) / frameInterval) * frameInterval;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const t = now / 1000;
    focusK = lerp(focusK, focus ? 1 : 0, 1 - Math.pow(0.02, dt));
    updateFocusPose();
    camera.position.lerpVectors(ROOM_POS, FOCUS_POS, focusK);
    camLook.lerpVectors(ROOM_LOOK, FOCUS_LOOK, focusK);
    camera.position.x += Math.sin(t * 0.3) * 0.02 * (1 - focusK); camera.position.y += Math.sin(t * 0.23) * 0.015 * (1 - focusK);
    camera.lookAt(camLook);
    camera.updateMatrixWorld();
    for (const c of chars.values()) updateChar(c, dt, t);
    { const on = jukebox.playing, k = on ? 0.5 + 0.5 * Math.sin(t * 5.2) : 0;
      jbx.light.intensity = on ? 1.2 + 0.8 * k : 0; jbx.group.position.y = 1.72 + (on ? 0.004 * k : 0);
      jbx.group.rotation.z = on ? Math.sin(t * 5.2) * 0.012 : 0; }
    setHover(tagHover && !focus ? { kind: "agent", name: tagHover } : pickAt(pointer));
    if (!screenActive) drawTerm(now);
    renderer.render(scene, camera);
    if (screenActive) { overlay.style.transform = quadTransform(overlayW, overlayH, screenQuad()); }
  }
  requestAnimationFrame(frame);

  return {
    setAgents, say, quiet,
    nod(name) { const c = chars.get(name); if (c) c.nodUntil = performance.now() + 700; },
    typingCount() { let n = 0; for (const c of chars.values()) if (c.working && c.arrived && !c.saying) n++; return n; },
    setScreen(active) { screenActive = active; overlay.style.display = active ? "block" : "none"; if (!active) lines.length = 0; },
    setFocus, get focused() { return focus; },
  };
}
