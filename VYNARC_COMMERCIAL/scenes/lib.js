// Building blocks shared by the six scenes.
import * as THREE from 'three';
import { clamp, lerp } from '../animations/easing.js';

export const BRAND = {
  bg: '#05030B', bg2: '#10091D', violet: '#8B3DFF', neon: '#B45CFF', deep: '#491A85',
  silver: '#C9C7D8', text: '#F5F3FA', text2: '#92909F',
};
// THREE.Color parses CSS hex as sRGB and stores it in the linear working space
// (ColorManagement is on by default), so no extra conversion is needed.
export const lin = (hex) => new THREE.Color(hex);

const ADD = { blending: THREE.AdditiveBlending, transparent: true, depthWrite: false };
const PREMUL = {
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
  blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
  blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
  transparent: true, depthWrite: false,
};

export async function loadShaders(names) {
  const out = {};
  await Promise.all(names.map(async (n) => {
    const r = await fetch(`../shaders/${n}`);
    if (!r.ok) throw new Error('shader ' + n);
    out[n] = await r.text();
  }));
  return out;
}

export async function loadTexture(renderer, url, { premultiply = true, srgb = true, mips = true } = {}) {
  const img = await new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = () => rej(new Error('img ' + url));
    i.src = url;
  });
  const t = new THREE.Texture(img);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.premultiplyAlpha = premultiply;
  t.generateMipmaps = mips;
  t.minFilter = mips ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.needsUpdate = true;
  t.userData.w = img.naturalWidth; t.userData.h = img.naturalHeight;
  return t;
}

// ---------------------------------------------------------------- ribbon
export class Ribbon {
  constructor(S, { segments = 240, core = BRAND.neon, glow = BRAND.deep, silver = BRAND.silver } = {}) {
    this.n = segments;
    const n = segments + 1;
    const g = new THREE.BufferGeometry();
    this.pos = new Float32Array(n * 2 * 3);
    this.nrm = new Float32Array(n * 2 * 3);
    const uv = new Float32Array(n * 2 * 2);
    const idx = [];
    for (let i = 0; i < n; i++) {
      uv.set([i / segments, -1, i / segments, 1], i * 4);
      if (i < segments) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    }
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute('aNormal', new THREE.BufferAttribute(this.nrm, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(idx);
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['ribbon.vert'], fragmentShader: S['ribbon.frag'], side: THREE.DoubleSide, ...ADD,
      uniforms: {
        uCore: { value: lin(core) }, uGlow: { value: lin(glow) }, uSilver: { value: lin(silver) },
        uIntensity: { value: 1 }, uHead: { value: 1.2 }, uTail: { value: -0.2 }, uHeadGlow: { value: 0 },
        uCoreOffset: { value: 0.45 }, uCoreWidth: { value: 0.08 }, uSoftness: { value: 2.2 },
        uSilverAmt: { value: 0.6 }, uBodyAmt: { value: 0.7 }, uTime: { value: 0 },
      },
    });
    this.mesh = new THREE.Mesh(g, this.mat);
    this.mesh.frustumCulled = false;
    this._p = []; for (let i = 0; i < n; i++) this._p.push(new THREE.Vector3());
  }
  // pointFn(u) -> Vector3, widthFn(u) -> half width, twistFn(u) -> radians
  update(pointFn, widthFn, twistFn, upHint = new THREE.Vector3(0, 0, 1)) {
    const n = this.n + 1, P = this._p;
    for (let i = 0; i < n; i++) P[i].copy(pointFn(i / this.n));
    const T = new THREE.Vector3(), N = new THREE.Vector3(), B = new THREE.Vector3(), S = new THREE.Vector3(), NR = new THREE.Vector3();
    // initial frame
    T.subVectors(P[1], P[0]).normalize();
    N.copy(upHint).addScaledVector(T, -upHint.dot(T));
    if (N.lengthSq() < 1e-6) N.set(0, 1, 0).addScaledVector(T, -T.y);
    N.normalize();
    const prevT = T.clone();
    for (let i = 0; i < n; i++) {
      const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)];
      T.subVectors(b, a).normalize();
      // parallel transport
      const ax = new THREE.Vector3().crossVectors(prevT, T);
      const s = ax.length();
      if (s > 1e-6) { ax.normalize(); N.applyAxisAngle(ax, Math.asin(Math.min(1, s))); }
      prevT.copy(T);
      B.crossVectors(T, N).normalize();
      const u = i / this.n, tw = twistFn(u), w = widthFn(u);
      S.copy(N).multiplyScalar(Math.cos(tw)).addScaledVector(B, Math.sin(tw));
      NR.crossVectors(T, S).normalize();
      const p = P[i];
      this.pos.set([p.x - S.x * w, p.y - S.y * w, p.z - S.z * w, p.x + S.x * w, p.y + S.y * w, p.z + S.z * w], i * 6);
      this.nrm.set([NR.x, NR.y, NR.z, NR.x, NR.y, NR.z], i * 6);
    }
    const g = this.mesh.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.aNormal.needsUpdate = true;
  }
}

// --------------------------------------------------------------- environment
// Procedural studio for the metal: black void, lilac-white softbox above,
// neon-violet strip lights left/right, deep violet floor bounce.
export function buildEnvironment(renderer) {
  const scene = new THREE.Scene();
  // gradient dome: lilac-white sky, near-black horizon, violet floor bounce
  const dome = new THREE.SphereGeometry(30, 64, 32);
  const col = [];
  const p = dome.attributes.position;
  const top = lin('#efe6ff'), hor = lin('#0a0614'), flo = lin('#5a22a8'), front = lin('#cdb6ff');
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i) / 30, y = p.getY(i) / 30, z = p.getZ(i) / 30;
    const c = hor.clone();
    c.lerp(top.clone().multiplyScalar(2.6), Math.pow(clamp((y - 0.05) / 0.9), 0.8));
    c.add(flo.clone().multiplyScalar(1.4 * Math.pow(clamp((-y - 0.1) / 0.8), 1.2)));
    // soft frontal wash (behind the camera) so faces facing us get a gradient
    c.add(front.clone().multiplyScalar(0.55 * Math.pow(clamp(z), 3) * clamp(0.6 + y)));
    col.push(c.r, c.g, c.b);
  }
  dome.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  scene.add(new THREE.Mesh(dome, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
  const panel = (w, h, color, k, pos, look) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: lin(color).multiplyScalar(k), side: THREE.DoubleSide }));
    m.position.set(...pos); m.lookAt(...look); scene.add(m);
  };
  panel(3, 26, '#b45cff', 4.0, [-15, 2, 4], [0, 0, 0]);     // left neon strip
  panel(3, 20, '#8b3dff', 3.0, [15, -1, -3], [0, 0, 0]);    // right violet strip
  panel(12, 2.2, '#ffffff', 3.0, [4, 9, 13], [0, 0, 0]);    // front key kicker
  const pm = new THREE.PMREMGenerator(renderer);
  const rt = pm.fromScene(scene, 0.015);
  pm.dispose();
  return rt.texture;
}

function roundedShape(pts, r) {
  const s = new THREE.Shape();
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n];
    const d0 = new THREE.Vector2(p0[0] - p1[0], p0[1] - p1[1]);
    const d2 = new THREE.Vector2(p2[0] - p1[0], p2[1] - p1[1]);
    const rr = Math.min(r, d0.length() * 0.45, d2.length() * 0.45);
    d0.normalize(); d2.normalize();
    const a = [p1[0] + d0.x * rr, p1[1] + d0.y * rr];
    const b = [p1[0] + d2.x * rr, p1[1] + d2.y * rr];
    if (i === 0) s.moveTo(a[0], a[1]); else s.lineTo(a[0], a[1]);
    s.quadraticCurveTo(p1[0], p1[1], b[0], b[1]);
  }
  s.closePath();
  return s;
}

// shader injection: light sweep + noise materialisation with a hot edge
function injectLogoFX(mat, uniforms) {
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, uniforms);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vLogoPos;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvLogoPos = position;')
      .replace('#include <beginnormal_vertex>', '#include <beginnormal_vertex>\nobjectNormal = normalize(objectNormal + vec3(position.x * 0.14, position.y * 0.55, 0.0) * smoothstep(0.6, 0.95, abs(objectNormal.z)));');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 vLogoPos;
uniform float uMat; uniform float uSweep; uniform float uSweepAmt; uniform vec3 uEdge; uniform float uGlowAdd;
float lh(vec3 p){ p=fract(p*0.3183099+0.1); p*=17.0; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
float ln3(vec3 x){ vec3 i=floor(x), f=fract(x); f=f*f*(3.0-2.0*f);
 return mix(mix(mix(lh(i),lh(i+vec3(1,0,0)),f.x),mix(lh(i+vec3(0,1,0)),lh(i+vec3(1,1,0)),f.x),f.y),
            mix(mix(lh(i+vec3(0,0,1)),lh(i+vec3(1,0,1)),f.x),mix(lh(i+vec3(0,1,1)),lh(i+vec3(1,1,1)),f.x),f.y),f.z); }`)
      .replace('void main() {', `void main() {
  float mField = (vLogoPos.x * 0.42 - vLogoPos.y * 0.30) * 0.5 + 0.5 + (ln3(vLogoPos * 6.0) - 0.5) * 0.22;
  if (mField > uMat) discard;`)
      .replace('#include <opaque_fragment>', `#include <opaque_fragment>
  float sw = (vLogoPos.x * 0.8 + vLogoPos.y * 0.6 - uSweep) / 0.16;
  gl_FragColor.rgb += vec3(0.95, 0.9, 1.0) * exp(-sw * sw) * uSweepAmt;
  float edge = exp(-pow((uMat - mField) / 0.03, 2.0)) * step(uMat, 1.05);
  gl_FragColor.rgb += uEdge * edge * 6.0 + uEdge * uGlowAdd;`);
  };
}

// ----------------------------------------------------------- 3D VYNARC symbol
export class LogoSymbol3D {
  constructor(S, geo, envMap) {
    this.group = new THREE.Group();
    this.fx = {
      uMat: { value: 1.2 }, uSweep: { value: -5 }, uSweepAmt: { value: 0 },
      uEdge: { value: lin(BRAND.neon) }, uGlowAdd: { value: 0 },
    };
    const extrude = { depth: 0.16, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.03, bevelSegments: 6, curveSegments: 10, steps: 1 };
    const mk = (pts, color, rough, z) => {
      const g = new THREE.ExtrudeGeometry(roundedShape(pts, geo.corner_radius), extrude);
      g.translate(0, 0, -0.08);
      g.computeVertexNormals();
      const m = new THREE.MeshPhysicalMaterial({
        color: lin(color), metalness: 1.0, roughness: rough, envMap, envMapIntensity: 1.35,
        clearcoat: 1.0, clearcoatRoughness: 0.12, iridescence: 0.15, iridescenceIOR: 1.6,
      });
      injectLogoFX(m, this.fx);
      const mesh = new THREE.Mesh(g, m);
      mesh.position.z = z;
      this.group.add(mesh);
      return mesh;
    };
    this.left = mk(geo.left_stroke, '#dcd9ea', 0.13, -0.13);
    this.right = mk(geo.right_stroke, '#a26cff', 0.16, 0.13);
    // orbit arc
    this.orbit = new OrbitArc(S, geo);
    this.group.add(this.orbit.mesh);
  }
}

export class OrbitArc {
  constructor(S, geo, { radial = 18, segments = 220 } = {}) {
    const o = geo.orbit;
    this.o = o;
    const ratio = o.b / o.a;
    const u2 = new THREE.Vector3(o.u[0], o.u[1], 0);
    const w2 = new THREE.Vector3(o.u[1], -o.u[0], 0); // minor axis direction (y up)
    this.U = u2.clone();
    this.W = w2.clone().multiplyScalar(ratio).add(new THREE.Vector3(0, 0, -Math.sqrt(1 - ratio * ratio)));
    this.C = new THREE.Vector3(o.center[0], o.center[1], 0.2);
    this.Nrm = new THREE.Vector3().crossVectors(this.U, this.W).normalize();
    const pos = [], nrm = [], uv = [], idx = [];
    const th0 = o.theta_tail, th1 = o.theta_head + 0.02;
    for (let i = 0; i <= segments; i++) {
      const s = i / segments;
      const th = lerp(th0, th1, s);
      const c = this.point(th);
      const radialDir = this.U.clone().multiplyScalar(Math.cos(th)).add(this.W.clone().multiplyScalar(Math.sin(th))).normalize();
      // thickness: hair-thin tail, swelling to the head, rounded tip
      let r = o.max_thickness * 0.5 * (0.06 + 0.94 * Math.pow(clamp(s / 0.86), 1.7));
      if (s > 0.9) r *= Math.sqrt(Math.max(0, 1 - Math.pow((s - 0.9) / 0.1, 2)));
      for (let j = 0; j <= radial; j++) {
        const a = (j / radial) * Math.PI * 2;
        // flattened cross-section (a ribbon-like crescent): wide in the orbit plane
        const n = radialDir.clone().multiplyScalar(Math.cos(a)).add(this.Nrm.clone().multiplyScalar(Math.sin(a) * 0.55));
        pos.push(c.x + n.x * r, c.y + n.y * r, c.z + n.z * r);
        const nn = n.clone().normalize();
        nrm.push(nn.x, nn.y, nn.z);
        uv.push(s, j / radial);
      }
    }
    for (let i = 0; i < segments; i++) for (let j = 0; j < radial; j++) {
      const a = i * (radial + 1) + j, b = a + radial + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['orbit.vert'], fragmentShader: S['orbit.frag'], ...ADD,
      uniforms: {
        uCore: { value: lin(BRAND.neon) }, uRim: { value: lin(BRAND.violet) },
        uIntensity: { value: 1 }, uReveal: { value: 1.1 }, uPulse: { value: 0 },
      },
    });
    this.mesh = new THREE.Mesh(g, this.mat);
    this.mesh.frustumCulled = false;
  }
  point(th) {
    const o = this.o;
    return this.C.clone().addScaledVector(this.U, o.a * Math.cos(th)).addScaledVector(this.W, o.a * Math.sin(th));
  }
  // point along the visible arc, s in [0,1] tail->head (logo-local space)
  at(s) { return this.point(lerp(this.o.theta_tail, this.o.theta_head, s)); }
}

// --------------------------------------------------------- flat official logo
export class FlatLogo {
  constructor(S, tex, heightUnits = 1) {
    const ar = tex.userData.w / tex.userData.h;
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['basic_uv.vert'], fragmentShader: S['logo_flat.frag'], ...PREMUL, depthTest: false,
      uniforms: {
        map: { value: tex }, uOpacity: { value: 1 }, uReveal: { value: 1.3 }, uRevealSoft: { value: 0.08 },
        uSweep: { value: -1 }, uSweepAmt: { value: 0 }, uGlow: { value: 0 }, uBias: { value: 0 },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(heightUnits * ar, heightUnits), this.mat);
    this.mesh.frustumCulled = false;
  }
}

// ------------------------------------------------------------ glow sprite
export class Glow {
  constructor(S, color = BRAND.violet, size = 4, falloff = 3) {
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['basic_uv.vert'], fragmentShader: S['glow_sprite.frag'], ...ADD, depthTest: true,
      uniforms: { uColor: { value: lin(color) }, uIntensity: { value: 0 }, uFalloff: { value: falloff } },
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), this.mat);
    this.mesh.frustumCulled = false;
  }
  face(camera) { this.mesh.quaternion.copy(camera.quaternion); }
}

// --------------------------------------------------------------- text
// A line (or lines) of text rendered with the system Inter font into a
// canvas; every glyph becomes its own quad so letters can animate.
export class Text {
  constructor(S, lines, { size = 0.1, weight = 600, tracking = 0.18, color = BRAND.text, family = 'Inter', lineGap = 1.5 } = {}) {
    if (typeof lines === 'string') lines = [lines];
    const px = 200;
    const pad = 40;
    const cv = document.createElement('canvas');
    const ctx = cv.getContext('2d');
    const font = `${weight} ${px}px ${family}`;
    ctx.font = font;
    const trackPx = tracking * px;
    const lineW = lines.map((l) => [...l].reduce((w, ch) => w + ctx.measureText(ch).width + trackPx, -trackPx));
    const W = Math.ceil(Math.max(...lineW) + pad * 2);
    const lh = px * lineGap;
    const H = Math.ceil(lh * lines.length + pad * 2);
    cv.width = W; cv.height = H;
    ctx.font = font;
    ctx.fillStyle = '#fff';
    ctx.textBaseline = 'alphabetic';
    this.group = new THREE.Group();
    this.glyphs = [];
    const tex = new THREE.CanvasTexture(cv);
    tex.generateMipmaps = true;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.premultiplyAlpha = true;
    tex.anisotropy = 8;
    const scale = size / px;     // world units per canvas px
    let gi = 0;
    lines.forEach((line, li) => {
      let x = pad + (Math.max(...lineW) - lineW[li]) / 2;
      const yBase = pad + lh * li + px * 1.05;
      for (const ch of line) {
        const w = ctx.measureText(ch).width;
        ctx.fillText(ch, x, yBase);
        if (ch !== ' ') {
          const gx0 = x - 6, gx1 = x + w + 6, gy0 = yBase - px * 0.95, gy1 = yBase + px * 0.3;
          const g = new THREE.PlaneGeometry((gx1 - gx0) * scale, (gy1 - gy0) * scale);
          const uvs = g.attributes.uv;
          for (let k = 0; k < uvs.count; k++) {
            uvs.setXY(k, (uvs.getX(k) ? gx1 : gx0) / W, 1 - (uvs.getY(k) ? gy0 : gy1) / H);
          }
          const m = new THREE.ShaderMaterial({
            vertexShader: S['basic_uv.vert'], fragmentShader: S['text.frag'], ...PREMUL, depthTest: false,
            uniforms: { map: { value: tex }, uOpacity: { value: 1 }, uBias: { value: 0 }, uColor: { value: lin(color) }, uGlow: { value: 0.15 } },
          });
          const mesh = new THREE.Mesh(g, m);
          const cx = ((gx0 + gx1) / 2 - W / 2) * scale, cy = -((gy0 + gy1) / 2 - H / 2) * scale;
          mesh.position.set(cx, cy, 0);
          mesh.renderOrder = 50;
          mesh.frustumCulled = false;
          this.group.add(mesh);
          this.glyphs.push({ mesh, mat: m, base: new THREE.Vector3(cx, cy, 0), index: gi, line: li, ch });
          gi++;
        }
        x += w + trackPx;
      }
    });
    this.count = this.glyphs.length;
    this.width = Math.max(...lineW) * scale;
    this.height = lh * lines.length * scale;
  }
}

// --------------------------------------------------------------- UI panel
export class Panel {
  constructor(S, tex, widthUnits, { radius = 0.06, shadow = true, rim = 0.35 } = {}) {
    const ar = tex.userData.w / tex.userData.h;
    this.w = widthUnits; this.h = widthUnits / ar;
    this.group = new THREE.Group();
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['basic_uv.vert'], fragmentShader: S['panel.frag'], ...PREMUL, side: THREE.DoubleSide,
      uniforms: {
        map: { value: tex }, uOpacity: { value: 1 }, uBias: { value: 0 }, uSheen: { value: -1 }, uSheenAmt: { value: 0.0 },
        uDissolve: { value: 0 }, uSeed: { value: Math.random() * 10 }, uAspect: { value: ar }, uBright: { value: 1 },
        uRim: { value: rim }, uRimColor: { value: lin(BRAND.neon) },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(this.w, this.h), this.mat);
    this.mesh.frustumCulled = false;
    this.group.add(this.mesh);
    if (shadow) {
      const blur = Math.max(this.w, this.h) * 0.07;
      this.shMat = new THREE.ShaderMaterial({
        vertexShader: S['basic_uv.vert'], fragmentShader: S['shadow.frag'], ...PREMUL,
        uniforms: {
          uSize: { value: new THREE.Vector2(this.w, this.h) }, uRadius: { value: radius }, uBlur: { value: blur },
          uShadow: { value: 0.6 }, uGlow: { value: 0.045 }, uGlowColor: { value: lin(BRAND.violet) },
        },
      });
      this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(this.w + blur * 4, this.h + blur * 4), this.shMat);
      this.shadow.position.set(0, -this.h * 0.03, -0.06);
      this.shadow.frustumCulled = false;
      this.group.add(this.shadow);
    }
  }
  set opacity(v) { this.mat.uniforms.uOpacity.value = v; if (this.shMat) { this.shMat.uniforms.uShadow.value = 0.6 * v; this.shMat.uniforms.uGlow.value = 0.045 * v; } }
}

// ------------------------------------------------------- connection line
export class Line {
  constructor(S, { segments = 64, width = 0.03, color = BRAND.neon } = {}) {
    this.n = segments; this.width = width;
    const n = segments + 1;
    this.pos = new Float32Array(n * 2 * 3);
    const uv = new Float32Array(n * 4), idx = [];
    for (let i = 0; i < n; i++) {
      uv.set([i / segments, -1, i / segments, 1], i * 4);
      if (i < segments) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(idx);
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['line.vert'], fragmentShader: S['line.frag'], ...ADD, side: THREE.DoubleSide,
      uniforms: { uColor: { value: lin(color) }, uIntensity: { value: 1 }, uProgress: { value: 1.1 }, uPulse: { value: -1 }, uPulseAmt: { value: 0 } },
    });
    this.mesh = new THREE.Mesh(g, this.mat);
    this.mesh.frustumCulled = false;
  }
  // cubic bezier a -> b with sag/bow; camera-facing
  update(a, b, camPos, bow = new THREE.Vector3(0, 0.3, 0.2)) {
    const c1 = a.clone().lerp(b, 0.33).add(bow), c2 = a.clone().lerp(b, 0.66).add(bow);
    const P = (t) => {
      const it = 1 - t;
      return a.clone().multiplyScalar(it * it * it).addScaledVector(c1, 3 * it * it * t).addScaledVector(c2, 3 * it * t * t).addScaledVector(b, t * t * t);
    };
    const pts = [];
    for (let i = 0; i <= this.n; i++) pts.push(P(i / this.n));
    for (let i = 0; i <= this.n; i++) {
      const p = pts[i], T = pts[Math.min(this.n, i + 1)].clone().sub(pts[Math.max(0, i - 1)]).normalize();
      const V = camPos.clone().sub(p).normalize();
      const s = new THREE.Vector3().crossVectors(T, V).normalize().multiplyScalar(this.width);
      this.pos.set([p.x - s.x, p.y - s.y, p.z - s.z, p.x + s.x, p.y + s.y, p.z + s.z], i * 6);
    }
    this.mesh.geometry.attributes.position.needsUpdate = true;
  }
}

// ------------------------------------------------------------ particles
export class Particles {
  constructor(S, count) {
    this.count = count;
    const g = new THREE.BufferGeometry();
    this.pos = new Float32Array(count * 3);
    this.size = new Float32Array(count);
    this.alpha = new Float32Array(count);
    this.color = new Float32Array(count * 3);
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute('aSize', new THREE.BufferAttribute(this.size, 1));
    g.setAttribute('aAlpha', new THREE.BufferAttribute(this.alpha, 1));
    g.setAttribute('aColor', new THREE.BufferAttribute(this.color, 3));
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['particles.vert'], fragmentShader: S['particles.frag'], ...ADD,
      uniforms: { uScale: { value: 1000 } },
    });
    this.points = new THREE.Points(g, this.mat);
    this.points.frustumCulled = false;
  }
  commit() {
    const a = this.points.geometry.attributes;
    a.position.needsUpdate = true; a.aSize.needsUpdate = true; a.aAlpha.needsUpdate = true; a.aColor.needsUpdate = true;
  }
}

export class Backdrop {
  constructor(S) {
    this.mat = new THREE.ShaderMaterial({
      vertexShader: S['basic_uv.vert'], fragmentShader: S['backdrop.frag'], side: THREE.BackSide, depthWrite: false,
      uniforms: {
        uTime: { value: 0 }, uAmount: { value: 0 }, uDeep: { value: lin(BRAND.deep) }, uViolet: { value: lin(BRAND.violet) },
        uFocus: { value: new THREE.Vector3(0, 0.1, -1) },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(400, 48, 24), this.mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = -100;
  }
}
