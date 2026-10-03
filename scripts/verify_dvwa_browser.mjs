#!/usr/bin/env node
/** Verify authenticated navigation, security form and seeded benign vulnerability workflows. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output] = process.argv.slice(2);
if (!base || !output) throw new Error('Application origin and private output required');
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
page.on('pageerror', () => receipt.errors.push({ kind: 'browser-error' }));
page.on('requestfailed', (request) =>
  receipt.errors.push({ kind: 'transport-failure', path: new URL(request.url()).pathname }),
);
page.on('response', (response) => {
  if (response.status() >= 400)
    receipt.errors.push({ kind: 'response-error', path: new URL(response.url()).pathname, status: response.status() });
});
async function checked(name, terms) {
  await page.waitForFunction((terms) => terms.every((term) => document.body.innerText.includes(term)), terms, {
    timeout: 15000,
  });
  await page.waitForLoadState('load');
  const images = await page
    .locator('img')
    .evaluateAll((elements) => elements.every((image) => image.complete && image.naturalWidth > 0));
  const screenshot = `${name}.png`;
  await page.screenshot({ path: path.join(output, screenshot), fullPage: true });
  fs.chmodSync(path.join(output, screenshot), 0o600);
  receipt.checks.push({ name, passed: images, screenshot });
}
try {
  await page.goto(new URL('/dvwa/login.php', origin).href);
  await page.locator('input[name=username]').fill('admin');
  await page.locator('input[name=password]').fill('password');
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('login.php')),
    page.locator('input[name=Login]').click(),
  ]);
  await checked('authenticated-home', ['DVWA', 'Logout']);
  await page.goto(new URL('/dvwa/security.php', origin).href);
  await page.locator('select[name=security]').selectOption('low');
  await Promise.all([page.waitForNavigation(), page.locator('input[type=submit]').click()]);
  await checked('security-form', ['Security Level', 'low']);
  await page.goto(new URL('/dvwa/vulnerabilities/sqli/', origin).href);
  await page.locator('input[name=id]').fill('1');
  await Promise.all([page.waitForNavigation(), page.locator('input[name=Submit]').click()]);
  await checked('seeded-sql-page', ['First name', 'Surname']);
  await page.goto(new URL('/dvwa/vulnerabilities/xss_r/', origin).href);
  await page.locator('input[name=name]').fill('Synthetic Workflow');
  await Promise.all([page.waitForNavigation(), page.locator('input[type=submit]').click()]);
  await checked('reflected-form', ['Hello Synthetic Workflow']);
} catch {
  receipt.errors.push({ kind: 'workflow-assertion-failure' });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed =
    receipt.checks.length === 4 && receipt.checks.every((check) => check.passed) && !receipt.errors.length;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
