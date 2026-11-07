// Official VYNARC logo (untouched PNG) with a light sweep and a soft wipe-in.
// The artwork's pixels/geometry are never altered; light is only added on top,
// masked by the logo's own alpha.
uniform sampler2D map;
uniform float uOpacity;
uniform float uReveal;     // wipe position in uv.x (-0.2 .. 1.2)
uniform float uRevealSoft;
uniform float uSweep;      // light sweep position in uv.x
uniform float uSweepAmt;
uniform float uGlow;       // extra emission for bloom
uniform float uBias;
varying vec2 vUv;
void main() {
  vec4 c = texture(map, vUv, uBias);           // premultiplied
  float wipe = smoothstep(uReveal + uRevealSoft, uReveal - uRevealSoft, vUv.x + (vUv.y - 0.5) * 0.18);
  float s = (vUv.x + (0.5 - vUv.y) * 0.35 - uSweep) / 0.045;
  float sweep = exp(-s * s) * uSweepAmt;
  float lum = dot(c.rgb, vec3(0.3, 0.55, 0.15));
  vec3 rgb = c.rgb * (1.0 + uGlow) + vec3(0.92, 0.86, 1.0) * sweep * c.a * (0.6 + lum);
  // wipe edge glows violet while revealing
  float edge = exp(-pow((vUv.x + (vUv.y - 0.5) * 0.18 - uReveal) / (uRevealSoft * 0.6 + 1e-3), 2.0));
  rgb += vec3(0.55, 0.2, 1.0) * edge * c.a * 1.5 * step(0.001, uRevealSoft) * (1.0 - step(1.15, uReveal));
  float a = c.a * wipe * uOpacity;
  gl_FragColor = vec4(rgb * wipe * uOpacity, a);
}
