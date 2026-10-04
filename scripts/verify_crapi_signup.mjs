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
const receipt = { expected_negative: [], checks: [], errors: [], browser_closed: false, accepted: false };
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
  if (new URL(response.url()).pathname === '/crapi/mailhog/api/v2/jim' && response.status() === 404) {
    receipt.expected_negative.push({
      path: '/crapi/mailhog/api/v2/jim',
      status: 404,
      reason: 'pinned MailHog chaos monkey disabled',
    });
    return;
  }
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
  const finishedSignup = page
    .waitForEvent('requestfinished', {
      predicate: (request) => new URL(request.url()).pathname === '/crapi/identity/api/auth/signup',
      timeout: 15000,
    })
    .then(
      () => true,
      () => false,
    );
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/crapi/identity/api/auth/signup' && response.request().method() === 'POST',
  );
  const [response] = await Promise.all([
    responsePromise,
    page.locator('#basic').getByRole('button', { name: 'Signup', exact: true }).click(),
  ]);
  receipt.response = {
    status: response.status(),
    headers: Object.fromEntries(
      Object.entries(response.headers()).filter(([key]) =>
        ['content-type', 'content-length', 'transfer-encoding'].includes(key),
      ),
    ),
  };
  if (response.status() !== 200 || !response.headers()['content-type']?.includes('application/json'))
    throw new Error('Native signup response failed');
  await page.waitForFunction(() => document.body.innerText.includes('User Registered Successfully!'), undefined, {
    timeout: 15000,
  });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(output, 'signup-success.png'), fullPage: true });
  fs.chmodSync(path.join(output, 'signup-success.png'), 0o600);
  if (!(await finishedSignup)) throw new Error('Signup request completion failed');
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
  const login = async (password) => {
    const result = await context.request.post(new URL('/crapi/identity/api/auth/login', origin).href, {
      data: { email, password },
    });
    if (result.status() !== 200 || !result.headers()['content-type']?.includes('application/json'))
      throw new Error(
        `Isolated native login failed: ${result.status()} ${result.headers()['content-type']} ${(await result.text()).slice(0, 200)}`,
      );
    const document = await result.json();
    if (typeof document.token !== 'string' || !document.token) throw new Error('Origin-issued token missing');
    const parts = document.token.split('.');
    if (parts.length !== 3) throw new Error('Native JWT shape failed');
    const claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    if (claims.sub !== email) throw new Error('Native JWT actor changed');
    return document.token;
  };
  await login('Synthetic!123');
  receipt.checks.push({ name: 'signup-login', passed: true });
  const reset = await context.request.post(new URL('/crapi/identity/api/auth/forget-password', origin).href, {
    data: { email },
  });
  if (reset.status() !== 200 || (await reset.json()).message !== `OTP Sent on the provided email, ${email}`)
    throw new Error('Native reset request failed');
  let otp = '';
  for (let attempt = 0; attempt < 15; attempt++) {
    const result = await context.request.get(new URL('/crapi/mailhog/api/v2/messages?limit=1000', origin).href);
    if (result.status() !== 200) throw new Error('Native reset MailHog failed');
    const document = await result.json();
    const owned = document.items.filter((item) =>
      (item.Content.Headers.To || []).some((to) => to === email || to.endsWith(`<${email}>`)),
    );
    fixture.mail_ids = owned.map((item) => item.ID);
    journal();
    const resetMessages = owned.filter(
      (item) => JSON.stringify(item.Content.Headers.Subject) === JSON.stringify(['crAPI OTP']),
    );
    if (resetMessages.length > 1) throw new Error('Ambiguous reset mail');
    if (resetMessages.length === 1) {
      const raw = resetMessages[0].Raw.Data.split('\r\n\r\n').slice(1).join('\r\n\r\n');
      const body = raw
        .replace(/=\r?\n/g, '')
        .replace(/=([0-9A-F]{2})/g, (_match, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
      otp = body.match(/Your one time generated otp is:\s*(\d{4})(?!\d)/)?.[1] || '';
      if (!otp) throw new Error('Native labeled reset OTP missing');
      break;
    }
    await page.waitForTimeout(1000);
  }
  if (!otp) throw new Error('Native reset mail timeout');
  receipt.checks.push({ name: 'reset-mailhog', passed: true });
  const changed = await context.request.post(new URL('/crapi/identity/api/auth/v2/check-otp', origin).href, {
    data: { email, otp, password: 'SyntheticReset!123' },
  });
  if (changed.status() !== 200 || (await changed.json()).message !== 'OTP verified')
    throw new Error('Native password reset failed');
  await login('SyntheticReset!123');
  const oldLogin = await context.request.post(new URL('/crapi/identity/api/auth/login', origin).href, {
    data: { email, password: 'Synthetic!123' },
  });
  if (oldLogin.status() !== 401) throw new Error('Old password still accepted or rejection unverified');
  receipt.expected_negative.push({
    path: '/crapi/identity/api/auth/login',
    status: 401,
    reason: 'prior password invalidated by native reset',
  });
  receipt.checks.push({ name: 'reset-password-login', passed: true });

  await page.goto(new URL('/crapi/mailhog/', origin).href);
  await page.waitForFunction(() => document.body.innerText.includes('MailHog'), undefined, { timeout: 15000 });
  await page.screenshot({ path: path.join(output, 'mailhog.png'), fullPage: true });
  fs.chmodSync(path.join(output, 'mailhog.png'), 0o600);
  receipt.checks.push({ name: 'mailhog-render', passed: true, screenshot: 'mailhog.png' });
} catch (error) {
  receipt.rendered_text = (
    await page
      .locator('body')
      .innerText()
      .catch(() => '')
  ).slice(0, 2000);
  receipt.errors.push({ kind: 'workflow-assertion-failure', detail: String(error) });
} finally {
  await browser.close();
  receipt.browser_closed = true;
  receipt.passed = receipt.checks.length === 6 && !receipt.errors.length;
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, failures: receipt.errors.length }));
process.exitCode = receipt.passed ? 0 : 1;
