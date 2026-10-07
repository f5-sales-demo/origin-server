/** Verify wrong-content responses and broken images against an isolated HTTP fixture. */

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'origin-content-test-'));
const server = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'text/html');
  if (request.url === '/') response.end('<a href="/fixture/">fixture</a>');
  else response.end('<html><body>Origin Server<img src="/fixture/missing.png"></body></html>');
});
server.listen(0, '127.0.0.1');
await new Promise((resolve) => server.once('listening', resolve));
const manifest = {
  applications: [
    {
      id: 'fixture',
      prefix: '/fixture/',
      pages: [{ path: '', identity: 'Expected Application', content_type: 'text/html' }],
    },
  ],
};
fs.writeFileSync(path.join(temporary, 'manifest.json'), JSON.stringify(manifest));
try {
  const child = spawn(process.execPath, [
    new URL('../scripts/verify_content.mjs', import.meta.url).pathname,
    '--manifest',
    path.join(temporary, 'manifest.json'),
    '--output',
    path.join(temporary, 'evidence'),
    '--base',
    `http://127.0.0.1:${server.address().port}`,
  ]);
  child.stdout.pipe(process.stdout);
  child.stderr.pipe(process.stderr);
  const code = await new Promise((resolve) => child.on('exit', resolve));
  assert.equal(code, 1);
  const receipt = JSON.parse(fs.readFileSync(path.join(temporary, 'evidence/content-receipt.json')));
  assert.equal(receipt.content_passed, false);
  assert.equal(receipt.accepted, false);
  assert.equal(receipt.checks.find((check) => check.application === 'fixture').content_assertion, false);
  assert.equal(receipt.checks.find((check) => check.application === 'fixture').images[0].loaded, false);
} finally {
  server.close();
  fs.rmSync(temporary, { recursive: true, force: true });
}
