// Everything the Export button hands over, as one zip.
import { PLATES, makePlates, printPose, stlBytes } from './geometry.js';
import { channelsSvg, membraneSvg } from './svg.js';
import { zip } from './zip.js';

export async function exportFiles(wasm, lay, model, stem = 'layout', progress = () => {}) {
  const { plates, problems, worst } = await makePlates(wasm, model, { progress });
  const files = [];
  for (const plate of PLATES) {
    progress(`Writing ${stem}_${plate}.stl…`);
    const posed = printPose(plate, plates[plate], model);
    files.push({ name: `${stem}_${plate}.stl`, data: stlBytes(posed) });
    posed.delete();
    plates[plate].delete();
  }
  files.push({ name: `${stem}_membrane.svg`, data: membraneSvg(lay) });
  files.push({ name: `${stem}_channels.svg`, data: channelsSvg(lay, model) });
  const text = [...model.report];
  if (problems.length) text.push('', 'PROBLEMS FOUND BY THE CHECKS -- do not print until fixed:', ...problems.map((q) => `  ! ${q}`));
  else text.push('', 'Checks: every net is a separate sealed cavity; thinnest wall between two nets ' +
    Object.entries(worst).filter(([, v]) => v[1]).map(([k, v]) => `${k} ${v[0].toFixed(2)} mm`).join(', ') + '.');
  files.push({ name: `${stem}_README.txt`, data: text.join('\n') + '\n' });
  return { files, blob: zip(files), problems, worst };
}
