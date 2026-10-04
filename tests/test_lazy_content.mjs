/** Lazy viewport images must load; missing image responses must still fail. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'origin-lazy-test-'));
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=',
  'base64',
);
const server = http.createServer((request, response) => {
  if (request.url === '/fixture/pixel.png') {
    response.setHeader('Content-Type', 'image/png');
    response.end(png);
    return;
  }
  response.setHeader('Content-Type', 'text/html');
  if (request.url === '/') response.end('<a href="/fixture/">fixture</a>');
  else
    response.end(
      `<html><body>Expected Application<div style="height:2000px"></div><img id="lazy" width="30" height="30"><script>new IntersectionObserver((entries) => {if(entries[0].isIntersecting) document.querySelector('#lazy').src='/fixture/pixel.png';}).observe(document.querySelector('#lazy'));</script></body></html>`,
    );
});
server.listen(0, '127.0.0.1');
await new Promise((resolve) => server.once('listening', resolve));
fs.writeFileSync(
  path.join(temporary, 'manifest.json'),
  JSON.stringify({
    applications: [
      {
        id: 'fixture',
        prefix: '/fixture/',
        pages: [{ path: '', identity: 'Expected Application', content_type: 'text/html' }],
      },
    ],
  }),
);
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
  assert.equal(code, 0);
  const receipt = JSON.parse(fs.readFileSync(path.join(temporary, 'evidence/content-receipt.json')));
  assert.equal(receipt.content_passed, true);
  assert.equal(receipt.checks.find((check) => check.application === 'fixture').images[0].loaded, true);
} finally {
  server.close();
  fs.rmSync(temporary, { recursive: true, force: true });
}
