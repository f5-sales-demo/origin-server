#!/usr/bin/env node
/** Submit one journaled synthetic signup and verify its welcome MailHog message. */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [base, output] = process.argv.slice(2);
const origin = new URL(base);
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const id = crypto.randomUUID().replaceAll('-', '');
const email = `signup-${id}@example.com`;
const fixture = {
  email,
  number: `555${String(Number.parseInt(id.slice(0, 6), 16))
    .padStart(7, '0')
    .slice(-7)}`,
  vehicle_vin: null,
  mail_ids: [],
};
const journal = () =>
  fs.writeFileSync(path.join(output, 'fixture-journal.json'), JSON.stringify(fixture), { mode: 0o600 });
journal();
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
      ...(new URL(request.url()).origin === origin.origin ? { 'X-MUD-User': `benign-${id}` } : {}),
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
try {
  await page.goto(new URL('/crapi/signup', origin).href);
  await page.getByPlaceholder('Full Name').fill('Synthetic Signup');
  await page.getByPlaceholder('Email').fill(email);
  await page.getByPlaceholder('Phone No.').fill(fixture.number);
  await page.getByPlaceholder('Password', { exact: true }).fill('Synthetic!123');
  await page.getByPlaceholder('Re-enter Password').fill('Synthetic!123');
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/crapi/identity/api/auth/signup' && response.request().method() === 'POST',
  );
  const [response] = await Promise.all([
    responsePromise,
    page.locator('#basic').getByRole('button', { name: 'Signup', exact: true }).click(),
  ]);
  const result = await Promise.race([
    response.json(),
    new Promise((_resolve, reject) => setTimeout(() => reject(new Error('Signup response body timeout')), 15000)),
  ]);
  if (response.status() !== 200 || result.status !== 200 || !result.message.includes('registered successfully'))
    throw new Error('Native signup failed');
  await page.waitForFunction(() => document.body.innerText.includes('Please Login'), undefined, { timeout: 15000 });
  await page.screenshot({ path: path.join(output, 'signup-success.png'), fullPage: true });
  fs.chmodSync(path.join(output, 'signup-success.png'), 0o600);
  receipt.checks.push({ name: 'signup-submit', passed: true, screenshot: 'signup-success.png' });
  let messages = [];
  for (let attempt = 0; attempt < 15; attempt++) {
    const result = await context.request.get(new URL('/crapi/mailhog/api/v2/messages?limit=1000', origin).href);
    if (result.status() !== 200) throw new Error('MailHog route failed');
    const mail = await result.json();
    messages = mail.items.filter((item) => (item.Content.Headers.To || []).some((to) => to.includes(email)));
    if (messages.length) break;
    await page.waitForTimeout(1000);
  }
  if (messages.length !== 1) throw new Error('Signup mail identity failed');
  fixture.mail_ids = messages.map((item) => item.ID);
  const raw = messages[0].Raw.Data.split('\r\n\r\n').slice(1).join('\r\n\r\n');
  const body = raw
    .replace(/=\r?\n/g, '')
    .replace(/=([0-9A-F]{2})/g, (_match, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
  const vin = body.match(/VIN:[\s\S]*?>([A-HJ-NPR-Z0-9]{17})</);
  if (!vin) throw new Error('Welcome vehicle fixture missing');
  fixture.vehicle_vin = vin[1];
  journal();
  receipt.checks.push({ name: 'signup-mailhog', passed: true });
  await page.goto(new URL('/crapi/mailhog/', origin).href);
  await page.waitForFunction(() => document.body.innerText.includes('MailHog'), undefined, { timeout: 15000 });
  await page.screenshot({ path: path.join(output, 'mailhog.png'), fullPage: true });
  fs.chmodSync(path.join(output, 'mailhog.png'), 0o600);
  receipt.checks.push({ name: 'mailhog-render', passed: true, screenshot: 'mailhog.png' });
} catch (error) {
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed = receipt.checks.length === 3 && !receipt.errors.length;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
