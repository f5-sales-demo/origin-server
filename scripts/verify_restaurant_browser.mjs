#!/usr/bin/env node
/** Exercise local Swagger, OAuth password flow, seeded role profiles and ReDoc. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output] = process.argv.slice(2);
if (!base || !output) throw new Error('Application origin and evidence required');
const origin = new URL(base);
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const receipt = { checks: [], errors: [], browser_closed: false, accepted: false };
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
page.setDefaultTimeout(15000);
page.on('pageerror', () => receipt.errors.push({ kind: 'browser-error' }));
page.on('requestfailed', (request) =>
  receipt.errors.push({ kind: 'transport-failure', path: new URL(request.url()).pathname }),
);
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', path: new URL(response.url()).pathname, status: response.status() });
});
const url = (endpoint) => new URL('/restaurant/' + endpoint, origin).href;
async function checked(name, terms) {
  await page.waitForFunction((terms) => terms.every((term) => document.body.innerText.includes(term)), terms);
  await page.waitForLoadState('load');
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  const images = await page.locator('img').evaluateAll((elements) => elements.every((image) => image.naturalWidth > 0));
  const assets = await page
    .locator('script[src],link[href]')
    .evaluateAll((elements) => elements.map((element) => element.src || element.href));
  const local = assets.every((asset) => {
    const target = new URL(asset);
    return target.origin === origin.origin && target.pathname.startsWith('/restaurant/');
  });
  const screenshot = name + '.png';
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({
    name,
    passed: images && local,
    images,
    local,
    assets: assets.map((asset) => new URL(asset).pathname),
    screenshot,
  });
}
try {
  for (const role of ['customer', 'chef']) {
    await page.goto(url(''));
    await checked('swagger-' + role, ['Damn Vulnerable RESTaurant', '/restaurant/openapi.json', '/profile']);
    const servers = await page
      .locator('.servers select option')
      .evaluateAll((elements) => elements.map((element) => element.value));
    if (!servers.length || servers.some((server) => server !== '/restaurant'))
      throw new Error('Swagger server prefix failed');
    await page.getByRole('button', { name: 'Authorize', exact: true }).click();
    await page.locator('#oauth_username').fill('tgen_' + role);
    await page.locator('#oauth_password').fill('password');
    const tokenResponse = page.waitForResponse(
      (response) => response.url() === url('token') && response.request().method() === 'POST',
    );
    const [token] = await Promise.all([
      tokenResponse,
      page
        .locator('.dialog-ux button')
        .filter({ hasText: /^Authorize$/ })
        .click(),
    ]);
    const document = await token.json();
    if (token.status() !== 200 || !document.access_token) throw new Error('Swagger login failed');
    await page
      .locator('.dialog-ux button')
      .filter({ hasText: /^Close$/ })
      .click();
    const operation = page
      .locator('.opblock.opblock-get')
      .filter({ has: page.locator('.opblock-summary-path[data-path="/profile"]') });
    await operation.locator('.opblock-summary').click();
    await operation.getByRole('button', { name: 'Try it out', exact: true }).click();
    const profileResponse = page.waitForResponse(
      (response) => response.url() === url('profile') && response.request().method() === 'GET',
    );
    const [profile] = await Promise.all([
      profileResponse,
      operation.getByRole('button', { name: 'Execute', exact: true }).click(),
    ]);
    const data = await profile.json();
    if (profile.status() !== 200 || data.username !== 'tgen_' + role || data.role.toLowerCase() !== role)
      throw new Error('Swagger role profile failed');
    await checked('profile-' + role, ['tgen_' + role]);
  }
  await page.goto(url('redoc'));
  await checked('redoc', ['Damn Vulnerable RESTaurant', 'Get Profile', 'Get Menu']);
} catch (error) {
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 5 && receipt.checks.every((check) => check.passed) && !receipt.errors.length;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
