'use strict';

const fs = require('node:fs');
const net = require('node:net');
const Module = require('node:module');
const http = require('node:http');
const { AsyncLocalStorage } = require('node:async_hooks');
const requestContext = new AsyncLocalStorage();
let activeJournal = null;
let cache = null;
const SOCKET = '/tmp/waap-catalog-reviews.sock';
const MAX_INPUT = 16384;

function reviewIdentity(rows) {
  return rows
    .map(({ _id, author, product, message }) => ({ _id, author, product, message }))
    .sort((a, b) => String(a._id).localeCompare(String(b._id)));
}

class ReviewJournal {
  constructor(collection) {
    this.collection = collection;
    this.baseline = null;
    this.marker = null;
    this.restored = null;
    this.challengeChanges = new Map();
  }
  validate(marker) {
    if (!/^tgen-[a-f0-9]{32}$/.test(marker)) throw new Error('invalid marker');
  }
  recordChallenge(challenge, marker) {
    if (this.marker === null || !challenge) return;
    const previous = this.challengeChanges.get(challenge.id);
    if (marker !== this.marker) {
      if (previous) previous.foreign = true;
      return;
    }
    if (!previous && !challenge.solved)
      this.challengeChanges.set(challenge.id, { challenge, before: challenge.solved, foreign: false });
  }
  async snapshot(marker) {
    this.validate(marker);
    if (this.marker !== null) throw new Error('prior recovery required');
    this.baseline = await this.collection.find({});
    this.marker = marker;
    this.restored = null;
    this.challengeChanges.clear();
    this.notifications = cache ? cache.notifications.slice() : [];
    return { marker, reviews: reviewIdentity(this.baseline) };
  }
  async restore(marker) {
    this.validate(marker);
    if (this.marker === null && this.restored === marker) return { marker, restored: true, reviews: this.lastReviews };
    if (this.marker !== marker || this.baseline === null) throw new Error('journal identity changed');
    const current = await this.collection.find({});
    const baseline = new Map(this.baseline.map((row) => [row._id, row]));
    const patches = [];
    const removals = [];
    for (const row of current) {
      const before = baseline.get(row._id);
      if (before) {
        if (row.author !== before.author || row.product !== before.product) throw new Error('review identity changed');
        if (JSON.stringify(row.message) !== JSON.stringify(before.message)) {
          if (typeof row.message !== 'string' || !row.message.startsWith(marker + ':'))
            throw new Error('unowned review change');
          patches.push(before);
        }
      } else if (
        row.author === marker + '@example.com' ||
        (typeof row.message === 'string' && row.message.startsWith(marker + ':'))
      ) {
        if (row.author !== marker + '@example.com' && JSON.stringify(row.author) !== JSON.stringify({ $gt: '' }))
          throw new Error('review identity changed');
        removals.push(row);
      }
    }
    for (const before of baseline.values()) {
      if (!current.some((row) => row._id === before._id)) throw new Error('owned review missing');
    }
    for (const change of this.challengeChanges.values()) {
      if (change.foreign || change.challenge.solved !== true) throw new Error('challenge change ownership ambiguous');
    }
    for (const before of patches)
      await this.collection.update({ _id: before._id }, { $set: { message: before.message } });
    for (const row of removals) await this.collection.remove({ _id: row._id });
    const after = await this.collection.find({});
    if (
      after.some(
        (row) =>
          row.author === marker + '@example.com' ||
          (typeof row.message === 'string' && row.message.startsWith(marker + ':')),
      )
    )
      throw new Error('review restoration mismatch');
    for (const before of baseline.values()) {
      const row = after.find((r) => r._id === before._id);
      if (!row || JSON.stringify(row.message) !== JSON.stringify(before.message))
        throw new Error('review restoration mismatch');
    }
    for (const change of this.challengeChanges.values()) {
      change.challenge.solved = change.before;
      await change.challenge.save();
    }
    if (cache) {
      const ownedKeys = new Set([...this.challengeChanges.values()].map((change) => change.challenge.key));
      for (let i = cache.notifications.length - 1; i >= 0; i--) {
        if (ownedKeys.has(cache.notifications[i].key) && !this.notifications.includes(cache.notifications[i]))
          cache.notifications.splice(i, 1);
      }
    }
    const restoredChallenges = this.challengeChanges.size;
    this.challengeChanges.clear();
    this.marker = null;
    this.baseline = null;
    this.restored = marker;
    this.lastReviews = reviewIdentity(after.filter((row) => baseline.has(row._id)));
    return {
      marker,
      restored: true,
      reviews: this.lastReviews,
      restored_messages: patches.length,
      removed_reviews: removals.length,
      restored_challenges: restoredChallenges,
    };
  }
}

function start(collection, socketPath = SOCKET) {
  const journal = new ReviewJournal(collection);
  activeJournal = journal;
  let busy = false;
  const server = net.createServer({ allowHalfOpen: true }, (socket) => {
    let input = '';
    socket.setTimeout(30000, () => socket.destroy());
    socket.on('data', (bytes) => {
      input += bytes.toString('utf8');
      if (Buffer.byteLength(input) > MAX_INPUT) socket.destroy();
    });
    socket.on('end', async () => {
      if (busy) return socket.end(JSON.stringify({ passed: false }));
      busy = true;
      try {
        const value = JSON.parse(input);
        if (Object.keys(value).sort().join(',') !== 'action,marker' || !['snapshot', 'restore'].includes(value.action))
          throw new Error('invalid action');
        socket.end(JSON.stringify({ passed: true, ...(await journal[value.action](value.marker)) }));
      } catch {
        socket.end(JSON.stringify({ passed: false }));
      } finally {
        busy = false;
      }
    });
    socket.on('error', () => {});
  });
  if (fs.existsSync(socketPath)) {
    if (!fs.lstatSync(socketPath).isSocket()) throw new Error('unsafe review socket');
    fs.unlinkSync(socketPath);
  }
  server.listen(socketPath, () => fs.chmodSync(socketPath, 0o600));
  server.on('error', () => {
    process.exitCode = 1;
  });
  server.unref();
  return server;
}

function install() {
  const originalEmit = http.Server.prototype.emit;
  http.Server.prototype.emit = function (event, request, ...args) {
    if (event === 'request') {
      const marker = request.headers['x-tgen-family'];
      return requestContext.run(marker, () => originalEmit.call(this, event, request, ...args));
    }
    return originalEmit.call(this, event, request, ...args);
  };
  const original = Module._load;
  let attached = false;
  Module._load = function (request, parent, isMain) {
    const value = original.call(this, request, parent, isMain);
    if (value && value.challenges && Array.isArray(value.notifications)) cache = value;
    if (!attached && value && value.reviewsCollection && value.ordersCollection) {
      attached = true;
      start(value.reviewsCollection);
    }
    if (
      value &&
      typeof value.solve === 'function' &&
      typeof value.solveIf === 'function' &&
      !value.__waapJournalWrapped
    ) {
      value.__waapJournalWrapped = true;
      const solve = value.solve;
      value.solve = function (challenge, ...args) {
        if (activeJournal) activeJournal.recordChallenge(challenge, requestContext.getStore());
        return solve.call(this, challenge, ...args);
      };
    }
    return value;
  };
}

module.exports = { ReviewJournal, install, start };
