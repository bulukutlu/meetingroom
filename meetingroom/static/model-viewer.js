import * as THREE from 'three';
import { OrbitControls } from './vendor/addons/controls/OrbitControls.js';
import { STLLoader } from './vendor/addons/loaders/STLLoader.js';
import { OBJLoader } from './vendor/addons/loaders/OBJLoader.js';
import { GLTFLoader } from './vendor/addons/loaders/GLTFLoader.js';

const status = document.getElementById('status');
const params = new URLSearchParams(location.hash.slice(1));
const name = params.get('name') || '3D model';
document.getElementById('name').textContent = name;
let renderer, controls, observer, model, stopped = false;
const resources = new Set();

function dispose() {
  stopped = true;
  observer?.disconnect();
  controls?.dispose();
  model?.traverse(object => {
    if (object.geometry) resources.add(object.geometry);
    for (const material of object.material ? (Array.isArray(object.material) ? object.material : [object.material]) : []) {
      resources.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) resources.add(value);
    }
  });
  for (const resource of resources) resource.dispose();
  renderer?.dispose();
  renderer?.forceContextLoss();
}
window.addEventListener('pagehide', dispose, {once:true});

async function main() {
  const source = new URL(params.get('src') || '', location.href);
  // Only the room's authenticated file endpoint can supply a model.
  if (source.origin !== location.origin || !/^\/r\/[^/]+\/files\/[^/]+$/.test(source.pathname)) {
    throw new Error('Invalid shared model URL.');
  }
  renderer = new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x202936);
  document.body.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  const render = () => { if (!stopped) renderer.render(scene, camera); };
  controls.addEventListener('change', render);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x667088, 2.5));
  const key = new THREE.DirectionalLight(0xffffff, 3);
  key.position.set(3, 5, 4); scene.add(key);
  const fill = new THREE.DirectionalLight(0xc8ddff, 1.5);
  fill.position.set(-3, 1, -2); scene.add(fill);
  observer = new ResizeObserver(() => {
    renderer.setSize(innerWidth, innerHeight);
    camera.aspect = innerWidth / Math.max(innerHeight, 1);
    camera.updateProjectionMatrix(); render();
  });
  observer.observe(document.body);
  const response = await fetch(source);
  if (!response.ok) throw new Error(`Model download failed (${response.status}).`);
  const data = await response.arrayBuffer();
  const extension = name.split('.').pop().toLowerCase();
  if (extension === 'stl') {
    const geometry = new STLLoader().parse(data);
    const material = new THREE.MeshStandardMaterial({color:0x8fc7ed, roughness:0.65, side:THREE.DoubleSide, vertexColors:!!geometry.attributes.color});
    model = new THREE.Mesh(geometry, material);
  } else if (extension === 'obj') {
    model = new OBJLoader().parse(new TextDecoder().decode(data));
    model.traverse(object => {
      if (object.isMesh) {
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.side = THREE.DoubleSide;
      }
    });
  } else if (extension === 'glb') {
    const manager = new THREE.LoadingManager();
    // Embedded textures are supported; model references must not fetch other URLs.
    manager.setURLModifier(url => {
      if (/^(blob:|data:)/i.test(url)) return url;
      throw new Error('Use a GLB with embedded textures and buffers.');
    });
    model = (await new GLTFLoader(manager).parseAsync(data, '')).scene;
  } else throw new Error('Supported formats: STL, OBJ and GLB.');
  if (stopped) { dispose(); return; }
  const bounds = new THREE.Box3().setFromObject(model);
  const extent = bounds.getSize(new THREE.Vector3());
  const size = Math.max(extent.x, extent.y, extent.z);
  if (bounds.isEmpty() || !Number.isFinite(size) || size <= 0) throw new Error('The model has no visible geometry.');
  const center = bounds.getCenter(new THREE.Vector3());
  const root = new THREE.Group();
  root.add(model); root.scale.setScalar(2 / size);
  root.position.copy(center).multiplyScalar(-2 / size);
  scene.add(root);
  const reset = () => {
    const distance = 1.9 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / Math.min(camera.aspect, 1);
    camera.position.set(distance * 0.7, distance * 0.5, distance);
    camera.near = distance / 1000; camera.far = distance * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0); controls.update(); render();
  };
  document.getElementById('reset').onclick = reset;
  reset();
  status.textContent = 'Drag to orbit · Scroll or pinch to zoom · Right-drag to pan' + (extension === 'obj' ? ' · OBJ geometry only (no external materials)' : '');
}

main().catch(error => {
  status.textContent = `Cannot display model: ${error.message || error}`;
  dispose();
});
