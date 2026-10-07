import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'content-navigation-'));
let mutationHits = 0;
const server = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'text/html');
  if (request.url === '/') response.end('<a href="/fixture/">fixture</a>');
  else if (request.url === '/fixture/')
    response.end('<html><body>Fixture<a href="/fixture/difficulty/hard">Expert mode</a></body></html>');
  else {
    mutationHits++;
    response.end('<html>Fixture mode changed</html>');
  }
});
server.listen(0, '127.0.0.1');
await new Promise((resolve) => server.once('listening', resolve));
fs.writeFileSync(
  path.join(root, 'manifest.json'),
  JSON.stringify({
    applications: [
      {
        id: 'fixture',
        prefix: '/fixture/',
        pages: [{ path: '', content_type: 'text/html', identity: 'Fixture' }],
        mutation_paths: ['difficulty/hard'],
      },
    ],
  }),
);
try {
  const child = spawn(process.execPath, [
    new URL('../scripts/verify_content.mjs', import.meta.url).pathname,
    '--manifest',
    path.join(root, 'manifest.json'),
    '--output',
    path.join(root, 'evidence'),
    '--base',
    `http://127.0.0.1:${server.address().port}`,
  ]);
  child.stdout.pipe(process.stdout);
  child.stderr.pipe(process.stderr);
  const code = await new Promise((resolve) => child.once('exit', resolve));
  assert.equal(code, 0);
  assert.equal(mutationHits, 0, 'read-only crawl followed a state mutation');
  const receipt = JSON.parse(fs.readFileSync(path.join(root, 'evidence/content-receipt.json')));
  assert.equal(receipt.checks.find((check) => check.application === 'fixture').mutation_links.length, 1);
} finally {
  server.close();
  fs.rmSync(root, { recursive: true, force: true });
}
