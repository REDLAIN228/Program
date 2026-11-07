// Connection line: thin hot core, soft halo, travelling energy pulse, draw-on.
uniform vec3 uColor;
uniform float uIntensity;
uniform float uProgress;
uniform float uPulse;
uniform float uPulseAmt;
varying vec2 vUv;
void main() {
  float u = vUv.x, v = vUv.y;
  float draw = smoothstep(uProgress + 0.001, uProgress - 0.03, u);
  float core = exp(-v * v * 60.0);
  float halo = exp(-v * v * 5.0) * 0.28;
  float p = (u - uPulse) / 0.06;
  float pulse = exp(-p * p) * uPulseAmt;
  vec3 col = uColor * (core * (1.0 + pulse * 3.0) + halo * (1.0 + pulse));
  col += vec3(1.0, 0.9, 1.0) * core * pulse * 1.5;
  float ends = smoothstep(0.0, 0.04, u) * smoothstep(1.0, 0.96, u);
  gl_FragColor = vec4(col * draw * ends * uIntensity, 1.0);
}
