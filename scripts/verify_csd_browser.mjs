#!/usr/bin/env node
/** Verify display-only checkout state and restore only the run's synthetic receiver entries. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output, prefix = '/csd-demo/'] = process.argv.slice(2);
if (!base || !output || !['/', '/csd-demo/'].includes(prefix)) throw new Error('Declared CSD route required');
const origin = new URL(base);
const fixture = crypto.randomUUID();
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const receipt = {
  checks: [],
  errors: [],
  fixture_restored: false,
  browser_closed: false,
  csd_enabled: false,
  accepted: false,
};
const browser = await chromium.launch({
  headless: true,
  ...(process.env.ORIGIN_CHROMIUM_PATH ? { executablePath: process.env.ORIGIN_CHROMIUM_PATH } : {}),
});
const context = await browser.newContext();
const headers = { 'X-MUD-User': 'waap-workflow-benign', 'X-Demo-Fixture': fixture };
await context.route('**/*', async (route) => {
  const request = route.request();
  await route.continue({
    headers: { ...request.headers(), ...(new URL(request.url()).origin === origin.origin ? headers : {}) },
  });
});
const page = await context.newPage();
page.setDefaultTimeout(15000);
context.setDefaultTimeout(15000);
page.on('pageerror', () => receipt.errors.push({ kind: 'browser-error' }));
page.on('requestfailed', (request) =>
  receipt.errors.push({ kind: 'transport-failure', path: new URL(request.url()).pathname }),
);
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', status: response.status(), path: new URL(response.url()).pathname });
});
const url = (endpoint) => new URL(prefix + endpoint, origin).href;
async function logs() {
  const response = await context.request.get(url('exfil/log'), { headers });
  if (response.status() !== 200) throw new Error('Receiver log response failed');
  const entries = await response.json();
  if (!Array.isArray(entries)) throw new Error('Receiver log shape failed');
  return entries;
}
async function checked(name, terms) {
  await page.waitForFunction((terms) => terms.every((term) => document.body.innerText.includes(term)), terms);
  const escaped = await page.locator('a[href],script[src],form[action]').evaluateAll(
    (elements, prefix) =>
      elements.some((element) => {
        const target = new URL(element.href || element.src || element.action, location.href);
        return target.origin === location.origin && !target.pathname.startsWith(prefix);
      }),
    prefix,
  );
  const screenshot = `${name}.png`;
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, passed: !escaped, screenshot });
}
let baseline;
async function restore() {
  const response = await context.request.post(url('exfil/clear'), { headers });
  const result = await response.json();
  const remaining = await logs();
  return (
    response.status() === 200 &&
    result.status === 'cleared' &&
    !remaining.some((entry) => entry.fixture_id === fixture) &&
    baseline.every((entry) => remaining.some((item) => JSON.stringify(item) === JSON.stringify(entry)))
  );
}
try {
  baseline = await logs();
  const received = page.waitForResponse(
    (response) => response.url().startsWith(url('exfil?')) && response.request().method() === 'POST',
  );
  await page.goto(url(''));
  const response = await received;
  const document = await response.json();
  if (response.status() !== 200 || document.status !== 'received') throw new Error('Synthetic receiver failed');
  await checked('checkout', ['ShopDemo Checkout', 'Place Order']);
  const entries = await logs();
  if (!entries.some((entry) => entry.fixture_id === fixture && entry.attack_type === 'synthetic'))
    throw new Error('Synthetic receiver identity failed');
  await page.evaluate(() => updateCount());
  await page.waitForFunction(
    (count) => document.querySelector('#exfilCount').innerText === `${count} exfiltration(s) captured`,
    entries.length,
  );
  receipt.checks.push({ name: 'receiver-counter', passed: true });
  const fields = {
    firstName: 'Synthetic',
    lastName: 'Shopper',
    email: 'shopper@example.com',
    address: '1 Example Street',
    city: 'Example City',
    state: 'EX',
    zip: '00000',
    ccName: 'Synthetic Shopper',
    ccNumber: '4111111111111111',
    ccExpiry: '12/99',
    ccCvv: '999',
  };
  for (const [id, value] of Object.entries(fields)) await page.locator(`#${id}`).fill(value);
  await Promise.all([page.waitForURL(url('checkout-complete')), page.locator('button[type=submit]').click()]);
  await checked('checkout-complete', ['Synthetic checkout complete']);
  await page.locator(`a[href="${prefix}"]`).click();
  await page.locator(`a[href="${prefix}dashboard"]`).evaluate((link) => link.removeAttribute('target'));
  await page.locator(`a[href="${prefix}dashboard"]`).click();
  await checked('dashboard', ['Captured Data', 'synthetic demo data']);
  const cleared = page.waitForResponse(
    (response) => response.url() === url('exfil/clear') && response.request().method() === 'POST',
  );
  await page.locator('button', { hasText: 'Clear All' }).click();
  const clearResponse = await cleared;
  const afterClear = await logs();
  if (clearResponse.status() !== 200 || afterClear.some((entry) => entry.fixture_id === fixture))
    throw new Error('Native clear button failed');
  receipt.fixture_restored = await restore();
  receipt.checks.push({ name: 'scoped-clear', passed: receipt.fixture_restored });
} catch (error) {
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  try {
    if (baseline) receipt.fixture_restored = await restore();
  } catch {
    receipt.errors.push({ kind: 'fixture-restoration-failure' });
  }
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 5 &&
    receipt.checks.every((item) => item.passed) &&
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
