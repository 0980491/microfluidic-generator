// The 3D view: the real cavities (cut by manifold, the same geometry as the
// STL files) inside glass plates, one colour per line. Solid shows the plates
// as printed. Drag to orbit, right-drag to pan, wheel to zoom.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import { netColor, palette } from './colors.js';
import { PLATES, makePlates, netSolid } from './geometry.js';
import { SUPPLY } from './model.js';

const TINT = { bottom: '#4c6ef5', middle: '#2f9e44', top: '#e8590c' };
const SOLID = { bottom: '#bac8ff', middle: '#b2f2bb', top: '#ffd8a8' };
const VIEWS = {
  iso: [-0.62, -1.1, 0.95], top: [0, -0.0001, 1], front: [0, -1, 0.0001], side: [-1, 0, 0.0001], below: [0, -0.0001, -1],
};
const tick = () => new Promise((r) => setTimeout(r, 0));

function toGeometry(solid) {
  const mesh = solid.getMesh();
  const np = mesh.numProp, V = mesh.vertProperties;
  const pos = new Float32Array((V.length / np) * 3);
  for (let i = 0, j = 0; i < V.length; i += np, j += 3) { pos[j] = V[i]; pos[j + 1] = V[i + 1]; pos[j + 2] = V[i + 2]; }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(mesh.triVerts), 1));
  const out = toCreasedNormals(g, Math.PI / 5);
  g.dispose();
  return out;
}

export class Viewer3D {
  constructor(host, { panel, onExport }) {
    this.host = host; this.panel = panel;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    this.renderer.setClearColor(0x000000, 0);
    host.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    Object.assign(this.labels.domElement.style, { position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '1', overflow: 'hidden' });
    host.appendChild(this.labels.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 5000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener('change', () => this.render());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a96a8, 1.7));
    const sun = new THREE.DirectionalLight(0xffffff, 1.9); sun.position.set(-80, -140, 220); this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6); fill.position.set(120, 90, -60); this.scene.add(fill);
    this.mode = 'xray'; this.explode = 8; this.focus = null;
    this.vis = { top: true, middle: true, bottom: true, membranes: true, bolts: true, names: true };
    this.root = null; this.model = null;
    this._wire(onExport);
    new ResizeObserver(() => this.resize()).observe(host);
    // click a cavity to pick its line out
    let down = null;
    this.renderer.domElement.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    this.renderer.domElement.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !this.root) return;
      const r = this.renderer.domElement.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
      const hits = ray.intersectObjects(this.cavities.filter((m) => m.visible && !m.userData.dim), false);
      const net = hits[0]?.object.userData.net;
      this.pick(net ? this._legendKey(net) : null);
    });
  }

  _wire(onExport) {
    const p = this.panel;
    p.querySelectorAll('#mode3d button').forEach((b) => b.addEventListener('click', () => {
      p.querySelectorAll('#mode3d button').forEach((x) => x.classList.toggle('on', x === b));
      this.setMode(b.dataset.mode);
    }));
    p.querySelectorAll('#presets button').forEach((b) => b.addEventListener('click', () => this.view(b.dataset.p)));
    const ex = p.querySelector('#explode'), exv = p.querySelector('#explode-v');
    ex.addEventListener('input', () => { this.explode = +ex.value; exv.textContent = ex.value; this._layout(); });
    p.querySelectorAll('#chips button').forEach((b) => b.addEventListener('click', () => {
      this.vis[b.dataset.show] = !this.vis[b.dataset.show];
      b.classList.toggle('on', this.vis[b.dataset.show]);
      this._visibility();
    }));
    const tg = p.querySelector('#panel-toggle');
    const setCollapsed = (c) => { p.classList.toggle('collapsed', c); tg.textContent = c ? 'Show' : 'Hide'; };
    tg.addEventListener('click', () => setCollapsed(!p.classList.contains('collapsed')));
    setCollapsed(window.matchMedia('(max-width: 700px)').matches);
    this.legendEl = p.querySelector('#legend');
    this.infoEl = p.querySelector('#info3d');
  }

  clear() {
    if (this.root) {
      this.scene.remove(this.root);
      this.root.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); if (o.isCSS2DObject) o.element.remove(); });
    }
    this.root = null; this.model = null; this.solid = null;
    this.render();
  }

  async show(wasm, model, progress = () => {}) {
    this.clear();
    this.wasm = wasm; this.model = model;
    this.pal = palette([...model.routing.nets.keys()]);
    const root = this.root = new THREE.Group();
    this.groups = {}; this.cavities = []; this.shells = []; this.portLabels = []; this.nameLabels = []; this.boltObjs = [];
    const W = model.width, L = model.length;
    for (const plate of PLATES) {
      const g = new THREE.Group(); g.userData.plate = plate;
      this.groups[plate] = g; root.add(g);
      const t = model.thickness[plate], z0 = model.z0[plate];
      // glass shell
      const box = new THREE.BoxGeometry(W, L, t);
      const shell = new THREE.Mesh(box, new THREE.MeshStandardMaterial({ color: TINT[plate], transparent: true, opacity: 0.07, depthWrite: false, side: THREE.DoubleSide }));
      shell.position.set(W / 2, L / 2, z0 + t / 2); shell.renderOrder = 2;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: TINT[plate] }));
      edges.position.copy(shell.position);
      g.add(shell, edges); this.shells.push(shell, edges);
      // cavities, one mesh per net
      const nets = [...new Set(model.features.filter((f) => f.plate === plate && !f.net.startsWith('bolt')).map((f) => f.net))];
      progress(`Drawing the ${plate} plate (${nets.length} channels)…`);
      await tick();
      for (const net of nets) {
        const solid = netSolid(wasm, model, plate, net, false);
        const geo = toGeometry(solid); solid.delete();
        const isWindow = net.endsWith('.window');
        const mat = new THREE.MeshStandardMaterial({ color: netColor(net, this.pal), roughness: 0.42, metalness: 0.05,
          transparent: isWindow, opacity: isWindow ? 0.35 : 1, depthWrite: !isWindow });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.userData = { net, plate, base: isWindow ? 0.35 : 1 };
        g.add(mesh); this.cavities.push(mesh);
      }
      // bolt holes and nut pockets, faint
      const boltMat = new THREE.MeshStandardMaterial({ color: 0x868e96, transparent: true, opacity: 0.12, depthWrite: false });
      for (const f of model.features) {
        if (f.plate !== plate || !f.net.startsWith('bolt')) continue;
        const [x, y] = f.data.at;
        let m;
        if (f.kind === 'hole') {
          m = new THREE.Mesh(new THREE.CylinderGeometry(f.data.d / 2, f.data.d / 2, t, 24).rotateX(Math.PI / 2), boltMat);
          m.position.set(x, y, z0 + t / 2);
        } else {
          const cr = f.data.af / Math.sqrt(3);
          m = new THREE.Mesh(new THREE.CylinderGeometry(cr, cr, f.data.depth, 6).rotateX(Math.PI / 2), boltMat);
          m.position.set(x, y, f.data.z + f.data.depth / 2);
        }
        g.add(m); this.boltObjs.push(m);
      }
      // labels
      for (const f of model.features) {
        if (f.plate !== plate || f.kind !== 'port') continue;
        const el = document.createElement('div');
        el.className = 'label3d'; el.textContent = f.net; el.style.background = netColor(f.net, this.pal);
        const o = new CSS2DObject(el);
        const [sx, sy, sz] = f.data.start, [dx, dy] = f.data.dir;
        o.position.set(sx - dx * 3, sy - dy * 3, sz);
        o.userData.net = f.net;
        g.add(o); this.portLabels.push(o);
      }
    }
    for (const [name, [x, y]] of Object.entries(model.windows)) {
      const el = document.createElement('div'); el.className = 'label3d name'; el.textContent = name;
      const o = new CSS2DObject(el);
      o.position.set(x, y + model.windows[name][2] / 2 + 1.2, model.z0.top + model.thickness.top + 0.2);
      this.groups.top.add(o); this.nameLabels.push(o);
    }
    // the two membranes
    const memMat = new THREE.MeshStandardMaterial({ color: 0xf06595, transparent: true, opacity: 0.13, depthWrite: false, side: THREE.DoubleSide });
    this.membranes = [0, 1].map(() => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(W, L), memMat);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineDashedMaterial({ color: 0xf06595, dashSize: 1.5, gapSize: 1 }));
      e.computeLineDistances();
      const grp = new THREE.Group(); grp.add(m, e); grp.position.set(W / 2, L / 2, 0);
      root.add(grp); return grp;
    });
    this.scene.add(root);
    this.focus = null;
    this._legend();
    const T = model.thickness, r = model.routing;
    this.infoEl.textContent = `Plates ${W} × ${L} mm; bottom ${T.bottom}, middle ${T.middle}, top ${T.top} mm. ${model.actuation === 'vacuum' ? 'Negative pressure (bowls). ' : ''}Lines on ${r.levels} level${r.levels > 1 ? 's' : ''}. Click a channel to pick its line.`;
    this._layout();
    this.setMode(this.mode);
    this.resize();
    this.view('iso');
  }

  async setMode(mode) {
    this.mode = mode;
    if (mode === 'solid' && this.model && !this.solid) {
      this.infoEl.dataset.prev = this.infoEl.textContent;
      this.infoEl.textContent = 'Cutting the plates…';
      await tick();
      const { plates } = await makePlates(this.wasm, this.model, { check: false, fine: false });
      this.solid = {};
      for (const plate of PLATES) {
        const geo = toGeometry(plates[plate]); plates[plate].delete();
        const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: SOLID[plate], roughness: 0.75, metalness: 0 }));
        this.groups[plate].add(m); this.solid[plate] = m;
      }
      this.infoEl.textContent = this.infoEl.dataset.prev;
    }
    this._visibility();
  }

  _visibility() {
    if (!this.root) return;
    const xray = this.mode === 'xray';
    for (const p of PLATES) this.groups[p].visible = this.vis[p];
    for (const o of this.shells) o.visible = xray || o.isLineSegments;
    for (const m of this.cavities) m.visible = xray;
    for (const m of this.boltObjs) m.visible = xray && this.vis.bolts;
    if (this.solid) for (const p of PLATES) this.solid[p].visible = !xray;
    for (const m of this.membranes) m.visible = this.vis.membranes;
    for (const o of this.nameLabels) o.visible = this.vis.names && this.vis.top;
    for (const o of this.portLabels) o.visible = this.vis.names && this._active(o.userData.net);
    this.render();
  }

  _layout() {
    if (!this.root) return;
    const e = this.explode, Tm = this.model.thickness.middle;
    this.groups.bottom.position.z = -e; this.groups.middle.position.z = 0; this.groups.top.position.z = e;
    this.membranes[0].position.z = -e / 2; this.membranes[1].position.z = Tm + e / 2;
    this.render();
  }

  _legendKey(net) { return net.endsWith('.mid') ? '#mid' : net.endsWith('.out') || net.endsWith('.window') ? '#out' : net; }
  _active(net) { return this.focus === null || this._legendKey(net) === this.focus; }

  _legend() {
    const rows = [[SUPPLY, 'Supply (middle plate)', this.pal[SUPPLY]]];
    for (const [name, nr] of this.model.routing.nets) if (name !== SUPPLY)
      rows.push([name, `${name} · ${nr.members.length} valve${nr.members.length > 1 ? 's' : ''}`, this.pal[name]]);
    rows.push(['#mid', "Link between a cell's valves", netColor('x.mid', this.pal)], ['#out', 'Valve outlet → dome', netColor('x.out', this.pal)]);
    this.legendEl.innerHTML = '';
    for (const [key, label, col] of rows) {
      const d = document.createElement('div');
      d.innerHTML = `<i style="background:${col}"></i><span></span>`;
      d.querySelector('span').textContent = label;
      d.classList.toggle('on', this.focus === key);
      d.classList.toggle('off', this.focus !== null && this.focus !== key);
      d.addEventListener('click', () => this.pick(this.focus === key ? null : key));
      this.legendEl.appendChild(d);
    }
  }

  pick(key) {
    this.focus = key;
    for (const m of this.cavities) {
      const on = this._active(m.userData.net);
      m.userData.dim = !on;
      m.material.transparent = !on || m.userData.base < 1;
      m.material.opacity = on ? m.userData.base : 0.1;
      m.material.depthWrite = on && m.userData.base === 1;
      m.material.needsUpdate = true;
    }
    this._legend();
    this._visibility();
  }

  view(name) {
    if (!this.model) return;
    const m = this.model, W = m.width, L = m.length;
    const target = new THREE.Vector3(W / 2, L / 2, m.thickness.middle / 2);
    const span = Math.hypot(W, L, m.thickness.bottom + m.thickness.middle + m.thickness.top + 2 * this.explode);
    const dist = (span / 2) / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * 1.08;
    const dir = new THREE.Vector3(...VIEWS[name]).normalize();
    this.camera.position.copy(target).addScaledVector(dir, dist);
    this.controls.target.copy(target);
    this.camera.near = dist / 100; this.camera.far = dist * 10; this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
  }

  resize() {
    const r = this.host.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    this.renderer.setSize(r.width, r.height, false);
    this.renderer.domElement.style.width = `${r.width}px`; this.renderer.domElement.style.height = `${r.height}px`;
    this.labels.setSize(r.width, r.height);
    this.camera.aspect = r.width / r.height; this.camera.updateProjectionMatrix();
    this.render();
  }

  render() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
    });
  }
}
