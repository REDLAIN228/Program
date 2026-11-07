// Soft radial light (camera-facing quad). Used for atmosphere and light pools.
uniform vec3 uColor;
uniform float uIntensity;
uniform float uFalloff;
varying vec2 vUv;
void main() {
  vec2 d = vUv * 2.0 - 1.0;
  float r2 = dot(d, d);
  float e0 = exp(-uFalloff);
  float g = max(0.0, (exp(-r2 * uFalloff) - e0) / (1.0 - e0));
  g *= g * (3.0 - 2.0 * g) * 0.35 + 0.65 * g;
  gl_FragColor = vec4(uColor * g * uIntensity, 1.0);
}
