import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const files = JSON.parse(fs.readFileSync('provisioning/files.json', 'utf8'));
const template = files.find((item) => item.path.endsWith('csd-demo/templates/dashboard.html')).content;
const script = template.split('<script>')[1].split('</script>')[0].replaceAll('{{ request.script_root }}', '/csd-demo');

test('CSD clear refreshes content in place after a successful native clear', async () => {
  const calls = [];
  const container = { innerHTML: 'before' };
  const window = { document: { querySelector: () => container } };
  const context = vm.createContext({
    window,
    location: { pathname: '/csd-demo/dashboard', reload: () => assert.fail('unexpected navigation') },
    async fetch(url, options) {
      calls.push([url, options?.method || 'GET']);
      return { ok: true, text: async () => '<div>after</div>' };
    },
    DOMParser: class {
      parseFromString() {
        return { querySelector: () => ({ innerHTML: 'after' }) };
      }
    },
  });
  vm.runInContext(script, context);
  await vm.runInContext('clearAndReload()', context);
  assert.deepEqual(calls, [
    ['/csd-demo/exfil/clear', 'POST'],
    ['/csd-demo/dashboard', 'GET'],
  ]);
  assert.equal(container.innerHTML, 'after');
  assert.equal(window.dashboardRefreshComplete, 1);
});

test('CSD failed clear cannot claim refreshed state', async () => {
  const window = { document: { querySelector: () => assert.fail('unexpected refresh') } };
  const context = vm.createContext({ window, fetch: async () => ({ ok: false }) });
  vm.runInContext(script, context);
  await assert.rejects(vm.runInContext('clearAndReload()', context), /Receiver clear failed/);
  assert.equal(window.dashboardRefreshComplete, 0);
});
