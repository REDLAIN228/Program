// Anamorphic light streak: wide horizontal blur of the bright pass.
uniform sampler2D tSrc;
uniform vec2 uTexel;
uniform float uStep;
varying vec2 vUv;
void main() {
  vec3 c = vec3(0.0);
  float wsum = 0.0;
  for (int i = -7; i <= 7; i++) {
    float fi = float(i);
    float w = exp(-fi * fi / 18.0);
    vec2 o = vUv + vec2(fi * uStep * uTexel.x, 0.0);
    // small vertical spread so the streak has no hard top/bottom edge
    c += (texture(tSrc, o).rgb * 0.5 + texture(tSrc, o + vec2(0.0, uTexel.y)).rgb * 0.25
        + texture(tSrc, o - vec2(0.0, uTexel.y)).rgb * 0.25) * w;
    wsum += w;
  }
  gl_FragColor = vec4(c / wsum, 1.0);
}
