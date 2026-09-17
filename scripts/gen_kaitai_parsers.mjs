// Regenerate tests/kaitai/rekordbox_{pdb,anlz}.py from the vendored .ksy
// files. The .ksy sources come from Deep-Symmetry/crate-digger
// (src/main/kaitai/) at commit 7c9d5358d8a3ce663f566380f2dc79ab1393201e
// and are licensed EPL-2.0 OR MPL-2.0 OR LGPL-3.0-only.
//
// Usage (Node.js required, no Java needed):
//   npm install --prefix /tmp/ksc kaitai-struct-compiler@0.11.0 js-yaml
//   NODE_PATH=/tmp/ksc/node_modules node scripts/gen_kaitai_parsers.mjs
//
// Or keep node_modules next to this script.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const yaml = require('js-yaml');
const compiler = require('kaitai-struct-compiler');

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const kaitaiDir = path.join(root, 'tests', 'kaitai');
const ksyFiles = [
  path.join(kaitaiDir, 'rekordbox_pdb.ksy'),
  path.join(kaitaiDir, 'rekordbox_anlz.ksy'),
];

const importer = {
  importYaml(name) {
    return Promise.resolve(
      yaml.load(fs.readFileSync(path.join(kaitaiDir, name + '.ksy'), 'utf8'))
    );
  },
};

for (const f of ksyFiles) {
  const ksy = yaml.load(fs.readFileSync(f, 'utf8'));
  const files = await compiler.compile('python', ksy, importer, false);
  for (const [name, content] of Object.entries(files)) {
    const out = path.join(kaitaiDir, path.basename(name));
    fs.writeFileSync(out, content);
    console.log('wrote', out);
  }
}
