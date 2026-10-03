#!/usr/bin/env node
import crypto from 'node:crypto';
/** Render translated products, native login, seeded basket and supporting routes. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output, prefix = '/juice-shop/'] = process.argv.slice(2);
if (!base || !output) throw new Error('Application origin and private output required');
const origin = new URL(base);
if (!['/', '/juice-shop/'].includes(prefix)) throw new Error('Declared Juice Shop prefix required');
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const receipt = {
  checks: [],
  errors: [],
  websocket_frames: 0,
  browser_closed: false,
  accepted: false,
  verifier_sha256: crypto
    .createHash('sha256')
    .update(fs.readFileSync(new URL(import.meta.url)))
    .digest('hex'),
};
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
page.on('websocket', (socket) => {
  socket.on('framereceived', () => receipt.websocket_frames++);
  socket.on('socketerror', () => receipt.errors.push({ kind: 'socket-error' }));
});
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', path: new URL(response.url()).pathname, status: response.status() });
});
async function rendered(name, selector, terms) {
  await page.locator(selector).first().waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(
    ({ selector, terms }) => {
      const element = document.querySelector(selector);
      return element && terms.every((term) => element.innerText.includes(term));
    },
    { selector, terms },
    { timeout: 15000 },
  );
  await page.waitForTimeout(500);
  const screenshot = `${name}.png`;
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, passed: true, screenshot });
}
try {
  await page.goto(new URL(`${prefix}#/search`, origin).href, { waitUntil: 'domcontentloaded' });
  for (const name of ['Close Welcome Banner', 'dismiss cookie message'])
    await page
      .getByRole('button', { name })
      .click({ timeout: 1500 })
      .catch(() => {});
  await rendered('products', 'app-search-result', ['All Products', 'Apple Juice']);
  await page.locator('app-product img').evaluateAll(async (images) => {
    await Promise.all(
      images.map((image) =>
        image.complete
          ? Promise.resolve()
          : new Promise((resolve) => {
              image.addEventListener('load', resolve, { once: true });
              image.addEventListener('error', resolve, { once: true });
              setTimeout(resolve, 10000);
            }),
      ),
    );
  });
  const images = await page
    .locator('app-product img')
    .evaluateAll((elements) => elements.map((image) => image.complete && image.naturalWidth > 0));
  receipt.checks.push({ name: 'product-images', passed: images.length > 0 && images.every(Boolean) });
  await page.goto(new URL(`${prefix}#/login`, origin).href, { waitUntil: 'domcontentloaded' });
  await rendered('login-labels', 'app-login', ['Login', 'Email', 'Password']);
  await page.locator('#email').fill('admin@juice-sh.op');
  await page.locator('#password').fill('admin123');
  const [login] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `${prefix}rest/user/login` && response.request().method() === 'POST',
    ),
    page.locator('#loginButton').click(),
  ]);
  receipt.checks.push({ name: 'native-login', passed: login.status() === 200 });
  await page.goto(new URL(`${prefix}#/basket`, origin).href, { waitUntil: 'domcontentloaded' });
  await rendered('seeded-basket', 'app-basket', ['admin@juice-sh.op', 'Apple Juice', 'Total Price']);
  for (const [route, selector, terms] of [
    ['about', 'app-about', ['Customer Feedback']],
    ['contact', 'app-contact', ['Customer Feedback', 'CAPTCHA']],
    ['recycle', 'app-recycle', ['Request Recycling Box']],
    ['complain', 'app-complaint', ['Complaint']],
    ['score-board', 'app-score-board', ['Hacking Challenges', 'Coding Challenges']],
  ]) {
    await page.goto(new URL(`${prefix}#/${route}`, origin).href, { waitUntil: 'domcontentloaded' });
    await rendered(route, selector, terms);
  }
} catch {
  receipt.errors.push({ kind: 'workflow-assertion-failure' });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 10 &&
    receipt.checks.every((check) => check.passed) &&
    !receipt.errors.length &&
    receipt.websocket_frames > 0;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
