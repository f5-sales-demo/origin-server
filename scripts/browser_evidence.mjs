/** Shared image capture with an explicit text-only evidence mode. */
import fs from 'node:fs';
import path from 'node:path';

export const evidenceMode = process.env.ORIGIN_EVIDENCE_MODE ?? 'screenshots';
if (!['screenshots', 'text-only'].includes(evidenceMode)) throw new Error('Invalid evidence mode');

export async function captureScreenshot(page, output, name) {
  if (evidenceMode === 'text-only') return undefined;
  if (path.basename(name) !== name || !name.endsWith('.png')) throw new Error('Invalid screenshot name');
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  fs.chmodSync(path.join(output, name), 0o600);
  return name;
}
