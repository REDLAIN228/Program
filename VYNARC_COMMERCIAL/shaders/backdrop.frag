// Deep-space backdrop on a large inverted sphere: near-black with a faint,
// slowly breathing violet nebula and a horizon haze. Kept very dim on purpose.
uniform float uTime;
uniform float uAmount;
uniform vec3 uDeep;
uniform vec3 uViolet;
uniform vec3 uFocus;     // direction of the nebula core
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vViewDir;
float h31(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float n3(vec3 x) {
  vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(h31(i), h31(i + vec3(1,0,0)), f.x), mix(h31(i + vec3(0,1,0)), h31(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(h31(i + vec3(0,0,1)), h31(i + vec3(1,0,1)), f.x), mix(h31(i + vec3(0,1,1)), h31(i + vec3(1,1,1)), f.x), f.y), f.z);
}
void main() {
  vec3 dir = normalize(-vViewDir);
  float f = max(dot(dir, normalize(uFocus)), 0.0);
  float n = n3(dir * 3.0 + vec3(0.0, 0.0, uTime * 0.05)) * 0.6 + n3(dir * 7.0 - uTime * 0.03) * 0.4;
  float neb = pow(f, 6.0) * (0.55 + 0.45 * n);
  float haze = exp(-abs(dir.y + 0.15) * 7.0) * 0.25 * (0.6 + 0.4 * n);
  vec3 col = uDeep * (neb * 1.2 + haze) + uViolet * pow(f, 18.0) * 0.6 * n;
  gl_FragColor = vec4(col * uAmount, 1.0);
}
