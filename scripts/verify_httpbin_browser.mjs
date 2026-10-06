#!/usr/bin/env node
/** Exercise locally served Swagger and the native HTTP echo form. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output, prefix = '/httpbin/'] = process.argv.slice(2);
if (!base || !output || !['/', '/httpbin/'].includes(prefix)) throw new Error('Declared HTTPBin route required');
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
const url = (endpoint) => new URL(prefix + endpoint, origin).href;
async function checked(name, terms) {
  await page.waitForFunction((terms) => terms.every((term) => document.body.innerText.includes(term)), terms);
  await page.waitForLoadState('load');
  const escaped = await page.locator('a[href],script[src],link[href],form[action]').evaluateAll(
    (elements, prefix) =>
      elements.some((element) => {
        const target = new URL(element.href || element.src || element.action, location.href);
        return target.origin === location.origin && !target.pathname.startsWith(prefix);
      }),
    prefix,
  );
  const screenshot = name + '.png';
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, passed: !escaped, screenshot });
}
try {
  await page.goto(url(''));
  await checked('swagger', ['httpbin.org', 'HTTP Methods', 'Other Utilities']);
  const spec = await context.request.get(url('spec.json'));
  const definition = await spec.json();
  if (spec.status() !== 200 || definition.basePath !== prefix.replace(/\/$/, '') || !definition.paths['/post'])
    throw new Error('Swagger specification prefix failed');
  receipt.checks.push({ name: 'specification', passed: true });
  await page.locator(`a[href="${prefix}forms/post"]`).click();
  await checked('native-form', ['Customer name', 'Pizza Size', 'Submit order']);
  await page.locator('input[name=custname]').fill('Synthetic Shopper');
  await page.locator('input[name=custemail]').fill('shopper@example.com');
  await page.locator('input[name=size][value=medium]').check();
  await page.locator('textarea[name=comments]').fill('Synthetic form fixture');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === url('post') && response.request().method() === 'POST',
  );
  const [response] = await Promise.all([responsePromise, page.getByRole('button', { name: 'Submit order' }).click()]);
  const document = await response.json();
  if (
    response.status() !== 200 ||
    document.form.custname !== 'Synthetic Shopper' ||
    document.form.size !== 'medium' ||
    document.form.comments !== 'Synthetic form fixture'
  )
    throw new Error('Native echoed form failed');
  await checked('echoed-form', ['Synthetic Shopper', 'Synthetic form fixture']);
} catch (error) {
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 4 && receipt.checks.every((check) => check.passed) && !receipt.errors.length;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
