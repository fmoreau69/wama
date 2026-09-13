/**
 * WAMA — visionneuse d'objets 3D (module ES, brique COMMUNE — ROADMAP §17ter, trou 2).
 *
 * Rend un GLB/glTF (ou FBX) dans un conteneur : caméra cadrée sur la boîte englobante, orbite
 * à la souris, grille au sol, animations jouées si le fichier en porte. Le moteur est le three
 * VENDORISÉ (`common/_three_importmap.html`, règle pas-de-CDN) — le même que TalkingHead et
 * que le rendu 3D→2D à venir : vendoriser une fois sert les trois (jonction du 2026-08-19).
 *
 * Chargée à la DEMANDE par `media-preview.js` (`import('wama/3d-viewer')`) : la présence de
 * l'importmap sur la page EST la déclaration « cette page sait rendre du 3D » ; sans elle
 * l'import échoue et l'aperçu retombe sur le téléchargement, sans erreur.
 *
 *   const v = await Wama3DViewer.mount(hostEl, url, { format: 'glb' });
 *   v.dispose();   // à la fermeture de la modale — libère le contexte WebGL
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { FBXLoader } from 'three/addons/loaders/FBXLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const LOADERS = {
  glb: () => new GLTFLoader(),
  gltf: () => new GLTFLoader(),
  fbx: () => new FBXLoader(),
};

/** Formats que CETTE visionneuse sait rendre (les autres natures 3D — obj, stl, ply, usd — sont
 *  acceptées à l'ingest mais restent au téléchargement tant qu'un loader n'est pas vendorisé). */
export const RENDERABLE = Object.keys(LOADERS);

function formatOf(url, hint) {
  const f = String(hint || '').toLowerCase().replace(/^\./, '');
  if (f) return f;
  const m = /\.([a-z0-9]+)(?:[?#]|$)/i.exec(url || '');
  return m ? m[1].toLowerCase() : '';
}

export async function mount(host, url, opts) {
  opts = opts || {};
  const format = formatOf(url, opts.format);
  const make = LOADERS[format];
  if (!make) throw new Error('format 3D non rendu : ' + (format || '?'));

  const width = host.clientWidth || 640;
  const height = host.clientHeight || 420;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444466, 1.4));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(3, 6, 4);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 1000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  const loaded = await new Promise((resolve, reject) => {
    make().load(url, resolve, undefined, reject);
  });
  const root = loaded.scene || loaded;          // GLTFLoader rend {scene, animations}, FBX un Group
  scene.add(root);

  // Cadrage sur la boîte englobante : l'objet remplit la vue quelle que soit son échelle.
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 1e-3);
  const grid = new THREE.GridHelper(radius * 2, 10, 0x666688, 0x333344);
  grid.position.set(center.x, box.min.y, center.z);
  scene.add(grid);
  camera.position.set(center.x + radius * 0.9, center.y + radius * 0.6, center.z + radius * 1.6);
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();

  const clips = loaded.animations || [];
  let mixer = null;
  if (clips.length) {
    mixer = new THREE.AnimationMixer(root);
    mixer.clipAction(clips[0]).play();
  }

  const clock = new THREE.Clock();
  let alive = true;
  function frame() {
    if (!alive) return;
    requestAnimationFrame(frame);
    if (mixer) mixer.update(clock.getDelta());
    controls.update();
    renderer.render(scene, camera);
  }
  frame();

  const onResize = () => {
    const w = host.clientWidth || width, h = host.clientHeight || height;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = (typeof ResizeObserver !== 'undefined') ? new ResizeObserver(onResize) : null;
  if (ro) ro.observe(host);

  return {
    info: { format, meshes: countMeshes(root), animations: clips.map((c) => c.name),
            size: [size.x, size.y, size.z] },
    dispose() {
      alive = false;
      if (ro) ro.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) [].concat(o.material).forEach((m) => m && m.dispose && m.dispose());
      });
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    },
  };
}

function countMeshes(root) {
  let n = 0;
  root.traverse((o) => { if (o.isMesh) n += 1; });
  return n;
}
