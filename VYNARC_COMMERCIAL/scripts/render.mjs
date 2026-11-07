// Offline renderer: drives scenes/index.html in headless Chromium, renders
// frames deterministically by index and streams raw RGBA straight into FFmpeg.
//
//   node scripts/render.mjs --format landscape --width 3840 --height 2160 \
//        --start 0 --end 900 --out renders/chunks/landscape_000.mp4
//   node scripts/render.mjs --stills 0.5,2.4,5.8 --width 1280 --height 720 --outdir previews/stills
//
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { chromium, GL_ARGS } from './pw.mjs';
import { ROOT } from './serve.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : 'true']);
  return acc;
}, []));
const W = +(args.width || 1920), H = +(args.height || 1080), FPS = +(args.fps || 60);
const format = args.format || (W / H < 0.8 ? 'portrait' : W / H < 1.3 ? 'square' : 'landscape');
const crf = args.crf || '12';
const preset = args.preset || 'slow';

// ---- static server + frame sink on one port
let sink = null;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.frag': 'text/plain', '.vert': 'text/plain' };
const srv = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  if (req.method === 'POST' && u.pathname === '/frame') {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', async () => { await sink(Buffer.concat(chunks)); res.writeHead(204); res.end(); });
    return;
  }
  const f = path.join(ROOT, path.normalize(decodeURIComponent(u.pathname)));
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  fs.createReadStream(f).pipe(res);
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${srv.address().port}`;

const browser = await chromium.launch({ args: GL_ARGS });
const page = await browser.newPage({ viewport: { width: Math.min(W, 1920), height: Math.min(H, 1920) } });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(`${base}/scenes/index.html`);
await page.waitForFunction(() => window.VY_READY === true, null, { timeout: 60000 });
const info = await page.evaluate((o) => window.VY.init(o), {
  width: W, height: H, format, fps: FPS, msaa: +(args.msaa ?? 4), mbScale: +(args.mb ?? 1),
});
console.log('init', JSON.stringify(info), 'format', format);

async function renderAndPost(i) {
  return page.evaluate(async (i) => {
    const K = window.VY.frame(i);
    const t1 = performance.now();
    await fetch('/frame', { method: 'POST', body: window.VY.read() });
    window.VY.lastIo = performance.now() - t1;
    return K;
  }, i);
}

if (args.stills) {
  // PNG stills at given times (seconds) for review
  const outdir = path.resolve(ROOT, args.outdir || 'previews/stills');
  fs.mkdirSync(outdir, { recursive: true });
  for (const ts of args.stills.split(',').map(Number)) {
    const i = Math.round(ts * FPS);
    const file = path.join(outdir, `${format}_${String(i).padStart(4, '0')}.png`);
    await new Promise((resolve) => {
      sink = (buf) => new Promise((done) => {
        const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-i', '-', '-vf', 'vflip', '-frames:v', '1', file]);
        ff.on('close', () => { done(); resolve(); });
        ff.stdin.end(buf);
      });
      renderAndPost(i);
    });
    console.log('still', file);
  }
} else {
  const start = +(args.start || 0), end = +(args.end || Math.round(15 * FPS)), step = +(args.step || 1);
  const out = path.resolve(ROOT, args.out || `renders/chunks/${format}_${W}x${H}_${start}.mp4`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const vf = ['vflip'];
  const outFps = FPS / step;
  const enc = args.codec === 'ffv1'
    ? ['-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'yuv444p10le']
    : ['-c:v', 'libx264', '-preset', preset, '-crf', crf, '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-tune', 'film',
        '-x264-params', 'aq-mode=3:deblock=-1,-1', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709'];
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-r', String(outFps), '-i', '-',
    '-vf', vf.join(',') + ',scale=out_color_matrix=bt709:out_range=tv', ...enc, '-r', String(outFps), out], { stdio: ['pipe', 'inherit', 'inherit'] });
  sink = (buf) => new Promise((res) => { if (!ff.stdin.write(buf)) ff.stdin.once('drain', res); else res(); });
  const t0 = Date.now();
  let n = 0;
  for (let i = start; i < end; i += step) {
    const K = await renderAndPost(i);
    n++;
    if (n % 10 === 0 || i + step >= end) {
      const el = (Date.now() - t0) / 1000;
      const ms = await page.evaluate(() => [window.VY.lastMs | 0, window.VY.lastIo | 0]);
      console.log(`frame ${i} K=${K} render ${ms[0]}ms io ${ms[1]}ms ${(el / n).toFixed(2)}s/f  eta ${(((end - i) / step) * el / n / 60).toFixed(1)} min`);
    }
  }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
  console.log('wrote', out, `${((Date.now() - t0) / 1000).toFixed(0)}s`);
}
await browser.close();
srv.close();
