// Animation curves shared by every scene. All motion in the film is a pure
// function of time t (seconds), so any frame can be rendered independently
// and motion-blur sub-frames are exact.

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const mix3 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
export const smoothstep = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0));
  return t * t * (3 - 2 * t);
};

// CSS-style cubic-bezier(p1x, p1y, p2x, p2y), solved with Newton + bisection.
export function cubicBezier(p1x, p1y, p2x, p2y) {
  const cx = 3 * p1x, bx = 3 * (p2x - p1x) - cx, ax = 1 - cx - bx;
  const cy = 3 * p1y, by = 3 * (p2y - p1y) - cy, ay = 1 - cy - by;
  const sx = (t) => ((ax * t + bx) * t + cx) * t;
  const sy = (t) => ((ay * t + by) * t + cy) * t;
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x, d = dx(t);
      if (Math.abs(e) < 1e-6) return sy(t);
      if (Math.abs(d) < 1e-6) break;
      t -= e / d;
    }
    let lo = 0, hi = 1; t = x;
    for (let i = 0; i < 30; i++) {
      const v = sx(t);
      if (Math.abs(v - x) < 1e-6) break;
      if (v < x) lo = t; else hi = t;
      t = (lo + hi) / 2;
    }
    return sy(t);
  };
}

export const ease = {
  linear: (t) => t,
  // the house curve: soft start, long weightless settle
  cine: cubicBezier(0.45, 0.0, 0.15, 1.0),
  inOut: cubicBezier(0.65, 0.0, 0.35, 1.0),
  out: cubicBezier(0.16, 1.0, 0.3, 1.0),
  outSoft: cubicBezier(0.25, 0.8, 0.25, 1.0),
  in: cubicBezier(0.7, 0.0, 0.84, 0.0),
  inSoft: cubicBezier(0.5, 0.0, 0.75, 0.0),
  // "controlled overshoot": back-out limited to ~4%
  overshoot: (t) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    const s = 1.15;
    const u = t - 1;
    return 1 + (s + 1) * u * u * u + s * u * u;
  },
};

// progress of [t0,t1] with easing
export const seg = (t, t0, t1, e = ease.cine) => e(clamp((t - t0) / (t1 - t0)));
// fade in over [a,b], hold, fade out over [c,d]
export const window4 = (t, a, b, c, d, e = ease.inOut) =>
  Math.min(e(clamp((t - a) / (b - a))), 1 - e(clamp((t - c) / (d - c))));

// Critically damped spring response to a unit step at t0 (physical inertia).
export function spring(t, t0, omega = 9, zeta = 0.78) {
  const x = t - t0;
  if (x <= 0) return 0;
  if (zeta >= 1) return 1 - (1 + omega * x) * Math.exp(-omega * x);
  const wd = omega * Math.sqrt(1 - zeta * zeta);
  return 1 - Math.exp(-zeta * omega * x) * (Math.cos(wd * x) + (zeta * omega / wd) * Math.sin(wd * x));
}

// Deterministic hash noise
export function hash1(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
}
export function noise1(x) {
  const i = Math.floor(x), f = x - i;
  const u = f * f * (3 - 2 * f);
  return lerp(hash1(i), hash1(i + 1), u) * 2 - 1;
}
// smooth multi-octave drift used for "weightless" floating
export function drift(t, seed, amp = 1, freq = 0.35) {
  return amp * (noise1(t * freq + seed * 17.13) * 0.7 + noise1(t * freq * 2.1 + seed * 5.7) * 0.3);
}

// Uniform Catmull-Rom through key points [[t, x, y, z], ...] with eased time.
export function keyPath(keys, t) {
  if (t <= keys[0][0]) return keys[0].slice(1);
  const n = keys.length;
  if (t >= keys[n - 1][0]) return keys[n - 1].slice(1);
  let i = 0;
  while (i < n - 2 && t > keys[i + 1][0]) i++;
  const k0 = keys[Math.max(0, i - 1)], k1 = keys[i], k2 = keys[i + 1], k3 = keys[Math.min(n - 1, i + 2)];
  const u = (t - k1[0]) / (k2[0] - k1[0]);
  const out = [];
  for (let d = 1; d < k1.length; d++) {
    const p0 = k0[d], p1 = k1[d], p2 = k2[d], p3 = k3[d];
    // centripetal-ish tension 0.5 Catmull-Rom (C1 continuous => no velocity pops)
    const m1 = (p2 - p0) * 0.5 * ((k2[0] - k1[0]) / Math.max(1e-6, k2[0] - k0[0])) * 2;
    const m2 = (p3 - p1) * 0.5 * ((k2[0] - k1[0]) / Math.max(1e-6, k3[0] - k1[0])) * 2;
    const u2 = u * u, u3 = u2 * u;
    out.push((2 * u3 - 3 * u2 + 1) * p1 + (u3 - 2 * u2 + u) * m1 + (-2 * u3 + 3 * u2) * p2 + (u3 - u2) * m2);
  }
  return out;
}
