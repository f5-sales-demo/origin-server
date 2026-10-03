#!/usr/bin/env node
import crypto from 'node:crypto';
/** Render every declared application page and discovered same-origin navigation. */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const manifestPath = option('--manifest', '/opt/origin-server/applications.json');
const output = option('--output');
const bases = args.filter((_value, index) => args[index - 1] === '--base');
if (!output || bases.length === 0) throw new Error('--output and at least one --base are required');
const manifestBytes = fs.readFileSync(manifestPath);
const manifest = JSON.parse(manifestBytes);
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
fs.chmodSync(output, 0o700);
let browser;
const launchBrowser = () =>
  chromium.launch({
    headless: true,
    ...(process.env.ORIGIN_CHROMIUM_PATH ? { executablePath: process.env.ORIGIN_CHROMIUM_PATH } : {}),
  });
const receipt = {
  schema_version: 1,
  started: new Date().toISOString(),
  manifest_sha256: crypto.createHash('sha256').update(manifestBytes).digest('hex'),
  checks: [],
  workflow_acceptance: false,
  screenshots_reviewed: false,
};
try {
  browser = await launchBrowser();
  for (const base of bases) {
    const context = await browser.newContext();
    await context.route('**/*', async (route) => {
      const request = route.request();
      await route.continue({
        headers: {
          ...request.headers(),
          ...(new URL(request.url()).origin === new URL(base).origin ? { 'X-MUD-User': 'waap-content-benign' } : {}),
        },
      });
    });
    const landing = await context.newPage();
    try {
      const response = await landing.goto(new URL('/', base).href, { waitUntil: 'load', timeout: 30000 });
      const links = await landing
        .locator('a[href]')
        .evaluateAll((elements) =>
          elements.map((element) => new URL(element.getAttribute('href'), location.href).pathname),
        );
      const expected = manifest.applications.map((app) => app.prefix).sort();
      const hosted = links.filter((link) => link !== '/health').sort();
      receipt.checks.push({
        base,
        kind: 'landing-inventory',
        passed: response.status() === 200 && JSON.stringify(hosted) === JSON.stringify(expected),
        expected,
        observed: hosted,
      });
    } catch (error) {
      receipt.checks.push({ base, kind: 'landing-inventory', passed: false, error: String(error) });
    }
    await landing.close();
    for (const app of manifest.applications) {
      const queue = app.pages.map((page) => ({ url: new URL(app.prefix + page.path, base).href, contract: page }));
      const visited = new Set();
      while (queue.length) {
        const item = queue.shift();
        if (visited.has(item.url)) continue;
        if (visited.size >= 100) {
          receipt.checks.push({
            base,
            application: app.id,
            passed: false,
            error: 'navigation exceeds declared crawl bound',
          });
          break;
        }
        visited.add(item.url);
        const page = await context.newPage();
        const result = {
          base,
          application: app.id,
          url: item.url,
          console_errors: [],
          failed_requests: [],
          bad_responses: [],
          prefix_escapes: [],
          mutation_links: [],
        };
        page.on('pageerror', (error) => result.console_errors.push(String(error)));
        page.on('console', (message) => {
          if (message.type() === 'error') result.console_errors.push(message.text());
        });
        page.on('requestfailed', (request) =>
          result.failed_requests.push({ url: request.url(), error: request.failure()?.errorText }),
        );
        page.on('request', (request) => {
          const url = new URL(request.url());
          if (url.origin === new URL(base).origin && !url.pathname.startsWith(app.prefix))
            result.prefix_escapes.push(url.href);
        });
        page.on('response', (response) => {
          if (response.status() >= 400) result.bad_responses.push({ url: response.url(), status: response.status() });
        });
        try {
          const response = await page.goto(item.url, { waitUntil: 'load', timeout: 30000 });
          await page.locator('img').evaluateAll(async (images) => {
            await Promise.all(
              images.map((image) => {
                if (image.complete) return Promise.resolve();
                return new Promise((resolve) => {
                  image.addEventListener('load', resolve, { once: true });
                  image.addEventListener('error', resolve, { once: true });
                  setTimeout(resolve, 10000);
                });
              }),
            );
          });
          await page.waitForTimeout(2000);
          const body = await response.text();
          result.status = response.status();
          result.content_type = response.headers()['content-type'] ?? '';
          result.final_url = page.url();
          result.content_assertion =
            !item.contract ||
            (result.content_type.split(';')[0] === item.contract.content_type &&
              body.toLowerCase().includes(item.contract.identity.toLowerCase()));
          result.images = await page
            .locator('img')
            .evaluateAll((images) =>
              images.map((img) => ({ src: img.currentSrc, loaded: img.complete && img.naturalWidth > 0 })),
            );
          const navigation = await page
            .locator('a[href]')
            .evaluateAll((elements) => elements.map((element) => element.href));
          result.form_actions = await page
            .locator('form')
            .evaluateAll((elements) => elements.map((element) => element.action));
          for (const url of [...navigation, ...result.form_actions]) {
            const target = new URL(url);
            if (target.origin !== new URL(base).origin) continue;
            if (!target.pathname.startsWith(app.prefix)) result.prefix_escapes.push(url);
            else if ((app.mutation_paths ?? []).some((mutation) => target.pathname === app.prefix + mutation))
              result.mutation_links.push(url);
            else if (navigation.includes(url) && !target.href.includes('#')) queue.push({ url });
          }
          result.screenshot = `${app.id}-${crypto.createHash('sha256').update(item.url).digest('hex').slice(0, 16)}.png`;
          await page.screenshot({ path: path.join(output, result.screenshot), fullPage: true });
          fs.chmodSync(path.join(output, result.screenshot), 0o600);
          result.passed =
            result.status === 200 &&
            result.content_assertion &&
            result.images.every((img) => img.loaded) &&
            [result.console_errors, result.failed_requests, result.bad_responses, result.prefix_escapes].every(
              (errors) => errors.length === 0,
            );
        } catch (error) {
          result.passed = false;
          result.error = String(error);
        }
        receipt.checks.push(result);
        await page.close();
      }
    }
    await context.close();
  }
} finally {
  if (browser) await browser.close();
  receipt.completed = new Date().toISOString();
  receipt.content_passed = receipt.checks.length > 0 && receipt.checks.every((check) => check.passed);
  receipt.accepted = receipt.content_passed && receipt.workflow_acceptance && receipt.screenshots_reviewed;
  fs.writeFileSync(path.join(output, 'content-receipt.json'), JSON.stringify(receipt, null, 2), { mode: 0o600 });
}
console.log(
  JSON.stringify({
    content_passed: receipt.content_passed,
    accepted: receipt.accepted,
    failures: receipt.checks.filter((check) => !check.passed).length,
  }),
);
process.exitCode = receipt.content_passed ? 0 : 1;
