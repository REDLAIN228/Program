varying float vAlpha;
varying vec3 vColor;
void main() {
  vec2 d = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(d, d);
  if (r2 > 1.0) discard;
  float g = exp(-r2 * 4.0) + exp(-r2 * 30.0) * 0.8;
  gl_FragColor = vec4(vColor * g * vAlpha, 1.0);
}
