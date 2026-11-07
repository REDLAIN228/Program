// VYNARC commercial — offline renderer entry point.
// window.VY.init(opts) builds the world; window.VY.frame(i) renders frame i
// (pure function of time, so frames can be rendered in any order/process).
import * as THREE from 'three';
import { Post } from './post.js';
import { loadShaders, loadTexture, buildEnvironment, Backdrop } from './lib.js';
import { keyPath, seg, ease, clamp, window4 } from '../animations/easing.js';
import * as origin from './s1_origin.js';
import * as brand from './s2_brand.js';
import * as connect from './s3_connect.js';
import * as universe from './s4_universe.js';
import * as workflow from './s5_workflow.js';
import * as reveal from './s6_reveal.js';

const SHADER_FILES = [
  'fullscreen.vert', 'accum.frag', 'bloom_threshold.frag', 'bloom_down.frag', 'bloom_up.frag', 'streak.frag', 'composite.frag',
  'ribbon.vert', 'ribbon.frag', 'glow_sprite.frag', 'basic_uv.vert', 'orbit.vert', 'orbit.frag', 'logo_flat.frag', 'text.frag',
  'panel.frag', 'shadow.frag', 'line.vert', 'line.frag', 'particles.vert', 'particles.frag', 'backdrop.frag',
];
const TEXTURES = [
  'assets/vynarc_logo_trim.png', 'assets/ui_textures/hub.png', 'assets/ui_textures/preview.png', 'assets/ui_textures/dashboard_base.png',
  'assets/ui_textures/nc_projects.png', 'assets/ui_textures/nc_files.png', 'assets/ui_textures/nc_notes.png',
  'assets/ui_textures/nc_refs.png', 'assets/ui_textures/nc_links.png',
  ...['sidebar', 'topbar', 'hero', 'assistant', 'projects', 'pc1', 'pc2', 'pc3', 'pc4', 'activity', 'map', 'recent', 'templates', 'quick']
    .map((p) => `assets/ui_textures/part_${p}.png`),
];

// Vertical FOV per delivery format (k = horizontal coverage vs 16:9).
export const FORMATS = {
  landscape: { fov: 34, name: 'landscape' },
  square: { fov: 42, name: 'square' },
  portrait: { fov: 56, name: 'portrait' },
};

const SCENES = [origin, brand, connect, universe, workflow, reveal];

// motion-blur sub-samples by time: more where the camera or objects move fast
function subSamples(t) {
  if (t > 3.3 && t < 4.15) return 8;
  if (t > 6.45 && t < 7.2) return 8;
  if (t > 7.0 && t < 7.9) return 4;
  if (t > 9.95 && t < 10.9) return 4;
  if (t > 11.1 && t < 12.1) return 3;
  if (t > 12.0 && t < 13.0) return 4;
  if (t > 4.1 && t < 5.2) return 3;
  if (t > 1.2 && t < 2.2) return 3;
  return 2;
}

function gradeAt(t, frame) {
  // gentle exposure lift for the fly-through flash, final soft fade to black
  const flash = Math.exp(-Math.pow((t - 3.78) / 0.12, 2)) * 0.3 + Math.exp(-Math.pow((t - 7.03) / 0.1, 2)) * 0.1;
  const fade = 1 - seg(t, 14.35, 14.98, ease.inOut);
  const lift = Math.min(seg(t, 0.0, 0.25, ease.linear), 1 - seg(t, 14.75, 14.98, ease.linear));
  return {
    exposure: 1.0 + flash,
    bloom: 0.85,
    bloomThreshold: 0.95,
    bloomKnee: 0.5,
    streak: 0.05 + 0.07 * window4(t, 12.0, 12.4, 13.2, 13.8),
    vignette: 0.6,
    ca: 0.0018,
    grain: 0.018,
    fade, lift, frame,
  };
}

window.VY = {
  async init(opts = {}) {
    const W = opts.width || 1920, H = opts.height || 1080;
    this.fps = opts.fps || 60;
    this.duration = opts.duration || 15;
    this.mbScale = opts.mbScale ?? 1;
    const fmt = FORMATS[opts.format || 'landscape'];
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    canvas.style.width = '100vw'; canvas.style.height = '100vh';
    document.body.appendChild(canvas);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(1);
    renderer.setSize(W, H, false);
    renderer.autoClear = false;
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    this.renderer = renderer;

    const S = await loadShaders(SHADER_FILES);
    const tex = {};
    await Promise.all(TEXTURES.map(async (p) => {
      const key = p.split('/').pop().replace('.png', '');
      tex[key] = await loadTexture(renderer, `../${p}`);
    }));
    const geo = await (await fetch('../animations/logo_geometry.json')).json();
    const layout = await (await fetch('../assets/ui_textures/layout.json')).json();
    const timeline = await (await fetch('../animations/timeline.json')).json();

    const scene = new THREE.Scene();
    const overlay = new THREE.Scene();
    const aspect = W / H;
    const camera = new THREE.PerspectiveCamera(fmt.fov, aspect, 0.02, 1200);
    const ocam = new THREE.OrthographicCamera(-aspect, aspect, 1, -1, -10, 10);
    const envMap = buildEnvironment(renderer);
    const backdrop = new Backdrop(S);
    scene.add(backdrop.mesh);
    const halfH = Math.tan(THREE.MathUtils.degToRad(fmt.fov / 2));
    const ctx = {
      THREE, S, tex, geo, layout, timeline, scene, overlay, camera, ocam, renderer, envMap, backdrop,
      fmt, aspect, W, H, halfH, halfW: halfH * aspect,
      // horizontal coverage relative to the 16:9 master (for fitting wide content)
      k: (halfH * aspect) / (Math.tan(THREE.MathUtils.degToRad(17)) * (16 / 9)),
      portrait: aspect < 0.8, square: aspect >= 0.8 && aspect < 1.3,
    };
    this.ctx = ctx;
    this.scenes = SCENES.map((m) => m.create(ctx));
    // camera tracks: A = continuous journey (0..12), B = final reveal (12..15)
    this.trackA = [...origin.cameraKeys(ctx), ...brand.cameraKeys(ctx), ...connect.cameraKeys(ctx), ...universe.cameraKeys(ctx), ...workflow.cameraKeys(ctx)];
    this.trackB = reveal.cameraKeys(ctx);
    this.post = new Post(renderer, W, H, S, { msaa: opts.msaa ?? 4, bloomLevels: 7 });
    renderer.compile(scene, camera);
    return { W, H, frames: Math.round(this.duration * this.fps) };
  },

  setTime(t) {
    const ctx = this.ctx;
    const track = t < 12.0 ? this.trackA : this.trackB;
    const k = keyPath(track, t);
    ctx.camera.position.set(k[0], k[1], k[2]);
    ctx.camera.up.set(Math.sin(k[6] || 0), Math.cos(k[6] || 0), 0);
    ctx.camera.lookAt(k[3], k[4], k[5]);
    if (k[7]) { ctx.camera.fov = ctx.fmt.fov * k[7]; ctx.camera.updateProjectionMatrix(); }
    else if (ctx.camera.fov !== ctx.fmt.fov) { ctx.camera.fov = ctx.fmt.fov; ctx.camera.updateProjectionMatrix(); }
    ctx.camera.updateMatrixWorld();
    ctx.backdrop.mesh.position.copy(ctx.camera.position);
    ctx.backdrop.mesh.visible = ctx.backdrop.mat.uniforms.uAmount.value > 0.001;
    for (const s of this.scenes) s.update(t);
  },

  frame(i) {
    const t0 = performance.now();
    const t = i / this.fps;
    const K = Math.max(1, Math.round(subSamples(t) * this.mbScale));
    const shutter = 0.5 / this.fps; // 180-degree shutter
    const r = this.renderer, ctx = this.ctx;
    this.post.render(K, (s) => {
      const ts = K > 1 ? t + ((s + 0.5) / K - 0.5) * shutter : t;
      this.setTime(ts);
      r.setClearColor(0x000000, 1);
      r.clear();
      r.render(ctx.scene, ctx.camera);
      r.clearDepth();
      r.render(ctx.overlay, ctx.ocam);
    }, gradeAt(t, i));
    const gl = r.getContext(); const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    this.lastMs = performance.now() - t0;
    return K;
  },

  // raw RGBA of the canvas, bottom-up rows (ffmpeg -vf vflip)
  read() {
    const gl = this.renderer.getContext();
    const { W, H } = this.ctx;
    if (!this._buf) this._buf = new Uint8Array(W * H * 4);
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, this._buf);
    return this._buf;
  },
};
window.dispatchEvent(new Event('vy-ready'));
window.VY_READY = true;
