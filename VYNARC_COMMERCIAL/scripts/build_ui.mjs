// Renders assets/ui/vynarc_ui.html and captures every [data-shot] element and
// every dashboard [data-part] as transparent PNG textures + layout.json with
// their exact positions inside the 1672x941 dashboard.
import { chromium } from './pw.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { serve, ROOT } from './serve.mjs';

const SCALE = Number(process.env.UI_SCALE || 2.5);
const OUT = path.join(ROOT, 'assets/ui_textures');
fs.mkdirSync(OUT, { recursive: true });
const { srv, url } = await serve();
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1800, height: 3000 }, deviceScaleFactor: SCALE });
await page.goto(`${url}/assets/ui/vynarc_ui.html`);
await page.evaluate(() => window.iconsReady);
const layout = { scale: SCALE, dashboard: { w: 1672, h: 941 }, parts: {} };

for (const el of await page.$$('[data-shot]')) {
  const name = await el.getAttribute('data-shot');
  await el.screenshot({ path: path.join(OUT, `${name}.png`), omitBackground: true });
  console.log('shot', name);
}
const dash = await page.$('#dashboard');
const db = await dash.boundingBox();
const parts = await page.$$eval('[data-part]', (els) => els.map((e) => e.dataset.part));
for (const name of parts) {
  const el = await page.$(`[data-part="${name}"]`);
  const b = await el.boundingBox();
  layout.parts[name] = { x: b.x - db.x, y: b.y - db.y, w: b.width, h: b.height };
  await el.screenshot({ path: path.join(OUT, `part_${name}.png`), omitBackground: true });
  console.log('part', name, JSON.stringify(layout.parts[name]));
}
// the window background alone (all parts hidden) for the layered 3D build
await page.evaluate(() => document.querySelectorAll('#dashboard > .layer').forEach((e) => { e.style.visibility = 'hidden'; }));
await dash.screenshot({ path: path.join(OUT, 'dashboard_base.png'), omitBackground: true });
fs.writeFileSync(path.join(OUT, 'layout.json'), JSON.stringify(layout, null, 2));
await browser.close();
srv.close();
