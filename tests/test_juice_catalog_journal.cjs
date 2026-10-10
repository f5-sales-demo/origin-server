const assert = require('node:assert/strict');
const { test } = require('node:test');
const { ReviewJournal } = require('../scripts/juice_catalog_journal.cjs');

class Collection {
  constructor(rows) {
    this.rows = structuredClone(rows);
  }
  async find() {
    return structuredClone(this.rows);
  }
  async update(selector, patch) {
    const row = this.rows.find((r) => r._id === selector._id);
    Object.assign(row, patch.$set);
  }
  async remove(selector) {
    this.rows = this.rows.filter((r) => r._id !== selector._id);
  }
}

test('review journal restores only marked message changes and removes owned insertions', async () => {
  const marker = 'tgen-' + 'a'.repeat(32);
  const collection = new Collection([
    { _id: 'one', author: 'synthetic@example.com', message: 'baseline', likesCount: 0 },
  ]);
  const journal = new ReviewJournal(collection);
  await journal.snapshot(marker);
  collection.rows[0].message = marker + ':changed';
  collection.rows[0].likesCount = 1;
  collection.rows.push({ _id: 'two', author: marker + '@example.com', message: marker + ':owned' });
  collection.rows.push({ _id: 'foreign', author: 'foreign@example.com', message: 'unrelated' });
  const receipt = await journal.restore(marker);
  assert.equal(receipt.restored, true);
  assert.equal(collection.rows[0].message, 'baseline');
  assert.equal(collection.rows[0].likesCount, 1);
  assert.equal(
    collection.rows.some((r) => r._id === 'two'),
    false,
  );
  assert.equal(
    collection.rows.some((r) => r._id === 'foreign'),
    true,
  );
  assert.equal((await journal.restore(marker)).restored, true);
});

test('foreign overwrite and actor collision reject recovery before writes', async () => {
  const marker = 'tgen-' + 'a'.repeat(32);
  const collection = new Collection([{ _id: 'one', author: 'synthetic@example.com', message: 'baseline' }]);
  const journal = new ReviewJournal(collection);
  await journal.snapshot(marker);
  collection.rows[0].message = 'foreign change';
  await assert.rejects(journal.restore(marker), /unowned review change/);
  assert.equal(collection.rows[0].message, 'foreign change');
  collection.rows[0].message = marker + ':changed';
  collection.rows[0].author = 'foreign@example.com';
  await assert.rejects(journal.restore(marker), /review identity changed/);
});

test('unknown action, marker and concurrent active journal fail closed', async () => {
  const journal = new ReviewJournal(new Collection([]));
  await assert.rejects(journal.snapshot('foreign'), /invalid marker/);
  await journal.snapshot('tgen-' + 'a'.repeat(32));
  await assert.rejects(journal.snapshot('tgen-' + 'b'.repeat(32)), /prior recovery/);
  await assert.rejects(journal.restore('tgen-' + 'b'.repeat(32)), /journal identity/);
});

test('local socket permits fixed operations only and returns marker bound evidence', async () => {
  const fs = require('node:fs/promises');
  const net = require('node:net');
  const os = require('node:os');
  const path = require('node:path');
  const { start } = require('../scripts/juice_catalog_journal.cjs');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'juice-journal-'));
  const file = path.join(directory, 'journal.sock');
  const server = start(new Collection([]), file);
  await new Promise((resolve) => server.once('listening', resolve));
  function request(value) {
    return new Promise((resolve, reject) => {
      const client = net.createConnection(file);
      let response = '';
      client.on('connect', () => client.end(JSON.stringify(value)));
      client.on('data', (data) => (response += data.toString()));
      client.on('end', () => resolve(JSON.parse(response)));
      client.on('error', reject);
    });
  }
  try {
    assert.equal((await fs.stat(file)).mode & 0o077, 0);
    assert.equal((await request({ action: 'shell', marker: 'tgen-' + 'a'.repeat(32) })).passed, false);
    assert.equal((await request({ action: 'snapshot', marker: 'tgen-' + 'a'.repeat(32) })).passed, true);
    assert.equal((await request({ action: 'restore', marker: 'tgen-' + 'a'.repeat(32) })).restored, true);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await fs.rm(directory, { recursive: true });
  }
});

test('marked challenge solves restore only owned state and reject foreign conflicts', async () => {
  const marker = 'tgen-' + 'a'.repeat(32);
  const journal = new ReviewJournal(new Collection([]));
  const challenge = { id: 1, solved: false, async save() {} };
  await journal.snapshot(marker);
  journal.recordChallenge(challenge, marker);
  challenge.solved = true;
  const receipt = await journal.restore(marker);
  assert.equal(challenge.solved, false);
  assert.equal(receipt.restored_challenges, 1);
  await journal.snapshot(marker);
  journal.recordChallenge(challenge, marker);
  challenge.solved = true;
  journal.recordChallenge(challenge, 'foreign');
  await assert.rejects(journal.restore(marker), /ownership ambiguous/);
  assert.equal(challenge.solved, true);
});
