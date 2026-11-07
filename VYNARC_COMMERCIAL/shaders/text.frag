// Per-glyph text quad. Blur is done with mip bias (defocus), premultiplied out.
uniform sampler2D map;
uniform float uOpacity;
uniform float uBias;
uniform vec3 uColor;
uniform float uGlow;
varying vec2 vUv;
void main() {
  float a = texture(map, vUv, uBias).a;
  gl_FragColor = vec4(uColor * (1.0 + uGlow) * a * uOpacity, a * uOpacity);
}
