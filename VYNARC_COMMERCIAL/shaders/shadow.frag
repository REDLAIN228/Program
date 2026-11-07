// Soft contact shadow + violet under-glow for floating panels (premultiplied).
uniform vec2 uSize;      // panel size in world units
uniform float uRadius;
uniform float uBlur;
uniform float uShadow;
uniform float uGlow;
uniform vec3 uGlowColor;
varying vec2 vUv;
float sdRound(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main() {
  vec2 full = uSize + vec2(uBlur * 4.0);
  vec2 p = (vUv - 0.5) * full;
  float d = sdRound(p, uSize * 0.5, uRadius);
  float sh = 1.0 - smoothstep(-uBlur, uBlur * 1.6, d);
  float gl = exp(-max(d, 0.0) / (uBlur * 0.9)) * step(-0.02, d);
  float a = sh * uShadow;
  gl_FragColor = vec4(uGlowColor * gl * uGlow, a);
}
