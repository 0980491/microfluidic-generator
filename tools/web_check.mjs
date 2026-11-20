// The website and the desktop program must give the same plates.
// Routes every example with both (docs/js/route.js and the Python package),
// compares the channels coordinate for coordinate, then exports with the
// website code and runs its seal / wall checks.
//
//   cd tools && npm install && npm run check        (needs python with the package installed,
//                                                     or PYTHON=/path/to/python)
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Module from 'manifold-3d';
import { Layout } from '../docs/js/model.js';
import { routeLayout } from '../docs/js/route.js';
import { buildModel, makePlates } from '../docs/js/geometry.js';
import { exportFiles } from '../docs/js/export.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const files = fs.readdirSync(path.join(root, 'examples')).filter((f) => f.endsWith('.mfl')).map((f) => path.join(root, 'examples', f));
const py = `
import sys, json
sys.path.insert(0, ${JSON.stringify(path.join(root, 'src'))})
from mfcad_layout.model import Layout
from mfcad_layout.route import route_layout
out = {}
from mfcad_layout import build3d
for f in sys.argv[1:]:
    lay = Layout.load(f)
    r = route_layout(lay)
    vols = {}
    for mode in ("pressure", "vacuum"):
        lay.actuation = mode
        plates, _ = build3d.make_plates(build3d.build_model(lay, r), check=False)
        vols[mode] = {k: v.volume() for k, v in plates.items()}
    out[f] = {"ok": r.ok, "levels": r.levels, "nets": {k: v.paths for k, v in r.nets.items()}, "vols": vols}
print(json.dumps(out))`;
const ref = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', py, ...files], { encoding: 'utf8' }));
const wasm = await Module(); wasm.setup();
const r4 = (paths) => JSON.stringify(paths.map((p) => p.map((q) => q.map((v) => +v.toFixed(4)))));
let bad = 0;
for (const f of files) {
  const lay = Layout.fromDict(JSON.parse(fs.readFileSync(f, 'utf8')));
  const r = routeLayout(lay);
  const P = ref[f], diffs = [];
  if (r.ok !== P.ok || r.levels !== P.levels) diffs.push(`ok/levels js ${r.ok}/${r.levels} py ${P.ok}/${P.levels}`);
  for (const [n, paths] of Object.entries(P.nets)) if (!r.nets.has(n) || r4(r.nets.get(n).paths) !== r4(paths)) diffs.push(`${n} differs`);
  let problems = [];
  for (const mode of ['pressure', 'vacuum']) {
    lay.actuation = mode;
    if (!r.ok) break;
    const m = buildModel(lay, r);
    ({ problems } = await exportFiles(wasm, lay, m, 'check'));
    const { plates } = await makePlates(wasm, m, { check: false });
    for (const [k, solid] of Object.entries(plates)) {
      const v = solid.volume(), pv = P.vols[mode][k];
      if (Math.abs(v - pv) > 1e-6 * pv) diffs.push(`${mode} ${k} volume js ${v.toFixed(3)} py ${pv.toFixed(3)}`);
      solid.delete();
    }
    if (problems.length) break;
  }
  bad += diffs.length + problems.length;
  console.log(path.basename(f), diffs.length ? diffs : 'routes and plate volumes (positive and negative pressure) identical to Python', problems.length ? problems : 'export checks pass');
}
process.exit(bad ? 1 : 0);
