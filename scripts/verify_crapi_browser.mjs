#!/usr/bin/env node
/** Verify native login, seeded views and refresh without changing application data. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output] = process.argv.slice(2);
if (!base || !output) throw new Error('Application origin and private output directory are required');
const origin = new URL(base);
if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password)
  throw new Error('HTTP application origin without credentials is required');
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const receipt = {
  source_sha256: crypto
    .createHash('sha256')
    .update(fs.readFileSync(new URL(import.meta.url)))
    .digest('hex'),
  checks: [],
  browser_closed: false,
  errors: [],
  accepted: false,
};
const browser = await chromium.launch({
  headless: true,
  ...(process.env.ORIGIN_CHROMIUM_PATH ? { executablePath: process.env.ORIGIN_CHROMIUM_PATH } : {}),
});
const context = await browser.newContext({ extraHTTPHeaders: { 'X-MUD-User': 'waap-workflow-benign' } });
const page = await context.newPage();
const pending = new Set();
page.on('request', (request) => pending.add(request));
page.on('requestfinished', (request) => pending.delete(request));
page.on('requestfailed', (request) => pending.delete(request));
async function settled() {
  const deadline = Date.now() + 15000;
  while (pending.size && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 50));
  if (pending.size) throw new Error('Application requests did not complete before navigation');
}

page.on('pageerror', () => receipt.errors.push({ kind: 'browser-error' }));
page.on('requestfailed', (request) =>
  receipt.errors.push({ kind: 'transport-failure', path: new URL(request.url()).pathname }),
);
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', path: new URL(response.url()).pathname, status: response.status() });
});
async function rendered(name, route, selector, terms) {
  await page.waitForURL((url) => url.pathname === route, { timeout: 15000 });
  await page.locator(selector).first().waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(
    ({ selector, terms }) => {
      const element = document.querySelector(selector);
      return element && terms.every((term) => element.innerText.includes(term));
    },
    { selector, terms },
    { timeout: 15000 },
  );
  await page.waitForTimeout(1000);
  const images = await page
    .locator('img')
    .evaluateAll((elements) => elements.map((image) => ({ loaded: image.complete && image.naturalWidth > 0 })));
  await settled();
  const screenshot = `${name}.png`;
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, path: route, passed: images.every((image) => image.loaded), screenshot });
}
try {
  await page.goto(new URL('/crapi/', origin).href, { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('Email').fill('adam007@example.com');
  await page.getByPlaceholder('Password', { exact: true }).fill('adam007!123');
  await page.locator('#basic').getByRole('button', { name: 'Login', exact: true }).click();
  await rendered('vehicle', '/crapi/dashboard', '.vehicle-card', ['VIN:', 'Hyundai', 'Creta']);
  for (const [label, route, selector, terms] of [
    ['Community', '/crapi/forum', 'main', ['Forum', 'New Post', 'POSTED BY']],
    ['Shop', '/crapi/shop', 'main', ['Shop', 'Wheel', 'Seat']],
  ]) {
    await page.getByRole('menuitem', { name: label, exact: true }).click();
    await rendered(label, route, selector, terms);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await rendered(`${label}-refresh`, route, selector, terms);
  }
} catch {
  receipt.errors.push({ kind: 'workflow-assertion-failure' });
} finally {
  await settled().catch(() => receipt.errors.push({ kind: 'pending-request-cleanup' }));
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 5 && receipt.checks.every((check) => check.passed) && !receipt.errors.length;
  receipt.claim = 'native login and seeded read-only views; remaining workflows and serving layers unverified';
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
