"""Exercise native byte-range framing and full-response compression over HTTP."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const http = require('node:http');
const Module = require('node:module');
const vm = require('node:vm');
const zlib = require('node:zlib');
const fs = require('node:fs');
const fixture = Buffer.from('native Juice Shop response identity '.repeat(700));
const observed = [];
function compression(options = {}) {
  assert.equal(options.threshold, 2048);
  return (request, response) => {
    observed.push({url: request.url, range: request.headers.range});
    let body = fixture;
    if (request.headers.range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range);
      const first = Number(match[1]);
      const last = match[2] ? Number(match[2]) : fixture.length - 1;
      body = fixture.subarray(first, last + 1);
      response.statusCode = 206;
      response.setHeader('Content-Range', `bytes ${first}-${last}/${fixture.length}`);
    }
    if (options.filter(request, response)) {
      body = zlib.brotliCompressSync(body);
      response.setHeader('Content-Encoding', 'br');
    }
    response.setHeader('Content-Type', 'text/html');
    response.setHeader('Content-Length', String(body.length));
    response.end(body);
  };
}
compression.filter = () => true;
const originalLoad = Module._load;
Module._load = function(...args) {
  return args[0] === 'compression' ? compression : originalLoad.apply(this, args);
};
const records = JSON.parse(fs.readFileSync('provisioning/files.json', 'utf8'));
const adapter = records.find(row => row.path.endsWith('juice-shop-framing/preload.cjs')).content;
vm.runInNewContext(adapter.split("const fs = require('node:fs');")[0], {require});
const adapted = require('compression');
assert.equal(adapted.filter, compression.filter);
assert.equal(require('compression'), adapted);
const normal = adapted({threshold: 2048});
const rejected = adapted({threshold: 2048, filter: () => false});
const server = http.createServer((request, response) => {
  (request.url === '/uncompressed' ? rejected : normal)(request, response);
});
function get(port, target, range) {
  return new Promise((resolve, reject) => {
    const request = http.get({hostname: '127.0.0.1', port, path: target,
      headers: {'Accept-Encoding': 'br', ...(range ? {Range: range} : {})}}, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({status: response.statusCode,
        headers: response.headers, body: Buffer.concat(chunks)}));
      response.on('error', reject);
    });
    request.on('error', reject);
  });
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const port = server.address().port;
    const full = await get(port, '/x');
    assert.equal(full.status, 200);
    assert.equal(full.headers['content-encoding'], 'br');
    assert.deepEqual(zlib.brotliDecompressSync(full.body), fixture);
    for (const [range, first, last] of [['bytes=0-', 0, fixture.length - 1], ['bytes=4-20', 4, 20]]) {
      const result = await get(port, '/x', range);
      assert.equal(result.status, 206);
      assert.equal(result.headers['content-encoding'], undefined);
      assert.equal(result.headers['content-range'], `bytes ${first}-${last}/${fixture.length}`);
      assert.equal(Number(result.headers['content-length']), last - first + 1);
      assert.deepEqual(result.body, fixture.subarray(first, last + 1));
    }
    const unrelated = await get(port, '/uncompressed');
    assert.equal(unrelated.headers['content-encoding'], undefined);
    assert.deepEqual(unrelated.body, fixture);
    assert.deepEqual(observed, [{url: '/x', range: undefined}, {url: '/x', range: 'bytes=0-'},
      {url: '/x', range: 'bytes=4-20'}, {url: '/uncompressed', range: undefined}]);
    console.log(JSON.stringify({fullCompressionPreserved: true,
      completeAndPartialRangesExact: true, nativeRequestsPreserved: true,
      customFilterPreserved: true}));
  } finally {
    await new Promise(resolve => server.close(resolve));
    Module._load = originalLoad;
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


def test_native_ranges_use_the_advertised_representation():
    result = subprocess.run(  # noqa: S603 - owned HTTP fixture and declared adapter
        [shutil.which("node") or "/usr/bin/node", "-e", HARNESS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "fullCompressionPreserved": True,
        "completeAndPartialRangesExact": True,
        "nativeRequestsPreserved": True,
        "customFilterPreserved": True,
    }
