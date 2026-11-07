// Glass UI panel: real UI texture (premultiplied sRGB), depth-of-field via
// mip bias, travelling glass sheen, violet rim, and noise dissolve with a hot
// edge used when panels turn into particles.
uniform sampler2D map;
uniform float uOpacity;
uniform float uBias;
uniform float uSheen;
uniform float uSheenAmt;
uniform float uDissolve;   // 0 = solid, 1 = gone
uniform float uSeed;
uniform float uAspect;
uniform float uBright;
uniform float uRim;
uniform vec3 uRimColor;
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vViewDir;

float h21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), u.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { s += a * vnoise(p); p *= 2.03; a *= 0.5; } return s; }

void main() {
  vec4 c = texture(map, vUv, uBias);
  vec3 rgb = c.rgb * uBright;
  float a = c.a;
  // glass sheen
  float s = (vUv.x * 0.85 + (1.0 - vUv.y) * 0.45 - uSheen) / 0.16;
  rgb += vec3(0.80, 0.74, 1.0) * exp(-s * s) * uSheenAmt * a * 0.10 * (0.4 + c.a);
  // violet rim (thin glowing contour, strongest at grazing angles)
  vec2 e = min(vUv, 1.0 - vUv) * vec2(uAspect, 1.0);
  float rim = exp(-min(e.x, e.y) * 90.0) * a;
  rgb += uRimColor * rim * uRim;
  // dissolve
  if (uDissolve > 0.0) {
    float n = fbm(vUv * vec2(uAspect, 1.0) * 5.0 + uSeed) * 0.75 + (1.0 - vUv.x) * 0.25;
    float thr = uDissolve * 1.15 - 0.05;
    float keep = smoothstep(thr - 0.02, thr + 0.02, n);
    float edge = exp(-pow((n - thr) / 0.035, 2.0)) * step(0.001, uDissolve);
    rgb = rgb * keep + vec3(0.62, 0.30, 1.0) * edge * 3.0 * a;
    a = a * max(keep, edge * 0.6);
    rgb *= max(keep, edge);
  }
  gl_FragColor = vec4(rgb * uOpacity, a * uOpacity);
}
