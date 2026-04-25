import { readFileSync, writeFileSync } from 'node:fs';

const version = process.argv[2];
if (version === undefined || version === '') {
  console.error('Usage: node stamp-manifest.js <version>');
  process.exit(1);
}

const path = 'manifest.json';
const manifest = JSON.parse(readFileSync(path, 'utf8'));

manifest.version = version;
manifest.generated = new Date().toISOString();

writeFileSync(path, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Stamped manifest.json: version=${version} generated=${manifest.generated}`);
