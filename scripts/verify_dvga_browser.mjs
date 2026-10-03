#!/usr/bin/env node
/** Verify native paste forms and subscription delivery; remove only this run's synthetic paste. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output, prefix = '/dvga/'] = process.argv.slice(2);
if (!base || !output || !['/', '/dvga/'].includes(prefix)) throw new Error('Declared DVGA route required');
const origin = new URL(base);
const title = `Synthetic Browser ${crypto.randomUUID()}`;
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const receipt = { checks: [], errors: [], fixture_restored: false, browser_closed: false, accepted: false };
const browser = await chromium.launch({
  headless: true,
  ...(process.env.ORIGIN_CHROMIUM_PATH ? { executablePath: process.env.ORIGIN_CHROMIUM_PATH } : {}),
});
const context = await browser.newContext();
await context.route('**/*', async (route) => {
  const request = route.request();
  await route.continue({
    headers: {
      ...request.headers(),
      ...(new URL(request.url()).origin === origin.origin ? { 'X-MUD-User': 'waap-workflow-benign' } : {}),
    },
  });
});
const page = await context.newPage();
page.on('pageerror', () => receipt.errors.push({ kind: 'browser-error' }));
page.on('requestfailed', (request) =>
  receipt.errors.push({ kind: 'transport-failure', path: new URL(request.url()).pathname }),
);
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', path: new URL(response.url()).pathname, status: response.status() });
});
const url = (endpoint) => new URL(prefix + endpoint, origin).href;
async function checked(name, terms) {
  await page.waitForFunction((terms) => terms.every((term) => document.body.innerText.includes(term)), terms, {
    timeout: 15000,
  });
  await page.waitForLoadState('load');
  const images = await page
    .locator('img')
    .evaluateAll((elements) => elements.every((image) => image.complete && image.naturalWidth > 0));
  const escaped = await page.locator('a[href],script[src],link[href],img[src]').evaluateAll(
    (elements, prefix) =>
      elements.some((element) => {
        const target = new URL(element.href || element.src, location.href);
        return target.origin === location.origin && !target.pathname.startsWith(prefix);
      }),
    prefix,
  );
  const screenshot = `${name}.png`;
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, passed: images && !escaped, screenshot });
}
async function graphql(query, variables = {}) {
  const response = await context.request.post(url('graphql'), {
    data: { query, variables },
    headers: { 'X-MUD-User': 'waap-workflow-benign' },
  });
  const document = await response.json();
  if (response.status() !== 200 || document.errors || !document.data)
    throw new Error('GraphQL response contract failed');
  return document.data;
}
const fixturePath = path.join(output, 'fixture-journal.json');
function journal() {
  fs.writeFileSync(fixturePath, JSON.stringify({ title, id, restored: receipt.fixture_restored }), { mode: 0o600 });
}
let id;
let subscriber;
async function restoreFixture() {
  if (id) {
    const before = await graphql('query Fixture($id:Int!){paste(id:$id){id title}}', { id: Number(id) });
    if (before.paste?.title !== title) throw new Error('Fixture ownership mismatch');
    const removed = await graphql('mutation Cleanup($id:Int!){deletePaste(id:$id){result}}', { id: Number(id) });
    const after = await graphql('query Fixture($id:Int!){paste(id:$id){id title}}', { id: Number(id) });
    return removed.deletePaste?.result === true && after.paste === null;
  } else {
    const found = await graphql('query Fixture($title:String!){paste(title:$title){id title}}', { title });
    return found.paste === null;
  }
}
try {
  await page.goto(url(''));
  await checked('home', ['Damn Vulnerable GraphQL Application']);
  await page.locator(`a[href="${prefix}public_pastes"]`).click();
  await checked('public-pastes', ['Public Pastes']);
  await page.waitForFunction(() => document.querySelector('#public_gallery').innerText.trim().length > 0);
  subscriber = await context.newPage();
  subscriber.on('pageerror', () => receipt.errors.push({ kind: 'subscription-browser-error' }));
  subscriber.on('requestfailed', () => receipt.errors.push({ kind: 'subscription-transport-failure' }));
  subscriber.on('response', (response) => {
    if (response.status() >= 400)
      receipt.errors.push({ kind: 'subscription-response-error', status: response.status() });
  });
  await subscriber.goto(url('public_pastes'));
  await subscriber.waitForFunction(() => document.querySelector('#public_gallery').innerText.trim().length > 0);
  await page.locator(`a[href="${prefix}create_paste"]`).click();
  await checked('create-form', ['Create a Paste', 'Visibility', 'Your message']);
  await page.locator('#title').fill(title);
  await page.locator('#content').fill('Synthetic browser fixture content');
  await page.locator('#visibility').selectOption({ label: 'Public' });
  const responsePromise = page.waitForResponse(
    (response) => response.url() === url('graphql') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  const response = await responsePromise;
  const document = await response.json();
  id = document.data?.createPaste?.paste?.id;
  journal();
  if (response.status() !== 200 || document.errors || !id || document.data.createPaste.paste.title !== title)
    throw new Error('Native paste form failed');
  await checked('created-paste', ['Paste was created successfully']);
  await subscriber.waitForFunction(
    (title) => document.querySelector('#public_gallery').innerText.includes(title),
    title,
    { timeout: 15000 },
  );
  const screenshot = 'subscription-delivery.png';
  await subscriber.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name: 'subscription-delivery', passed: true, screenshot });
  await page.locator(`a[href="${prefix}public_pastes"]`).click();
  await checked('persisted-paste', [title, 'Synthetic browser fixture content']);
} catch (error) {
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  try {
    receipt.fixture_restored = await restoreFixture();
  } catch {
    receipt.errors.push({ kind: 'fixture-restoration-failure' });
  }
  if (subscriber) await subscriber.close();
  await browser.close();
  receipt.browser_closed = true;
  journal();
  receipt.passed =
    receipt.checks.length === 6 &&
    receipt.checks.every((check) => check.passed) &&
    !receipt.errors.length &&
    receipt.fixture_restored;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(
  JSON.stringify({
    passed: receipt.passed,
    checks: receipt.checks.length,
    failures: receipt.errors.length,
    fixture_restored: receipt.fixture_restored,
  }),
);
process.exitCode = receipt.passed ? 0 : 1;
