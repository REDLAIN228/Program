// The logo's orbit arc as a hot emissive tube: neon violet body, white-hot
// core towards the head, fresnel rim. uv.x along arc (tail 0 -> head 1).
uniform vec3 uCore;
uniform vec3 uRim;
uniform float uIntensity;
uniform float uReveal;     // 0..1 draw-on along the arc
uniform float uPulse;
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vViewDir;
varying vec3 vNormalW;
void main() {
  float u = vUv.x;
  float draw = smoothstep(uReveal + 0.002, uReveal - 0.04, u);
  float facing = abs(dot(normalize(vNormalW), normalize(vViewDir)));
  float heat = smoothstep(0.15, 0.95, u);
  vec3 body = mix(uRim, uCore, pow(facing, 1.5));
  vec3 hot = mix(body, vec3(1.0, 0.93, 1.0), pow(facing, 3.0) * heat * 0.85);
  float energy = mix(0.35, 3.2, pow(heat, 1.6)) * (1.0 + uPulse);
  gl_FragColor = vec4(hot * energy * uIntensity * draw, 1.0);
}
