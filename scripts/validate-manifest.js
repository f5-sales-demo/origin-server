import { readFileSync } from 'node:fs';

const path = 'manifest.json';
let manifest;
let errors = 0;

function fail(msg) {
  console.error(`FAIL: ${msg}`);
  errors++;
}

function pass(msg) {
  console.log(`PASS: ${msg}`);
}

try {
  manifest = JSON.parse(readFileSync(path, 'utf8'));
  pass('Valid JSON');
} catch (e) {
  fail(`Invalid JSON: ${e.message}`);
  process.exit(1);
}

if (manifest.component !== 'origin-server') fail('component must be "origin-server"');
else pass('component field correct');

if (typeof manifest.version !== 'string') fail('version must be a string');
else pass(`version: ${manifest.version}`);

if (manifest.connection?.health_check?.path !== '/health') fail('connection.health_check.path must be "/health"');
else pass('global health check path correct');

if (Array.isArray(manifest.applications) === false) {
  fail('applications must be an array');
  process.exit(1);
}
pass(`${manifest.applications.length} applications defined`);

const names = new Set();
for (const app of manifest.applications) {
  const prefix = `applications[${app.name}]`;

  if (typeof app.name !== 'string' || app.name === '') fail(`${prefix}: name is required`);
  if (names.has(app.name)) fail(`${prefix}: duplicate name`);
  names.add(app.name);

  if (typeof app.path !== 'string') fail(`${prefix}: path is required`);
  else if (app.path.startsWith('/') === false) fail(`${prefix}: path must start with /`);
  else if (app.path.endsWith('/') === false) fail(`${prefix}: path must end with /`);
  else pass(`${prefix}: path ${app.path}`);

  if (typeof app.description !== 'string' || app.description === '') fail(`${prefix}: description is required`);

  if (app.health_check?.path === undefined) fail(`${prefix}: health_check.path is required`);
  else if (app.health_check.path.startsWith(app.path) === false && app.health_check.path !== app.path)
    fail(`${prefix}: health_check.path "${app.health_check.path}" should start with app path "${app.path}"`);
  else pass(`${prefix}: health_check ${app.health_check.path}`);

  if (app.container?.image === undefined) fail(`${prefix}: container.image is required`);

  if (Array.isArray(app.demo_features) === false) fail(`${prefix}: demo_features must be an array`);
}

console.log(`\n${errors === 0 ? 'ALL PASSED' : `${errors} ERRORS`}`);
process.exit(errors === 0 ? 0 : 1);
