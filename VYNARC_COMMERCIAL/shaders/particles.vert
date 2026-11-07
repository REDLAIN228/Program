attribute float aSize;
attribute float aAlpha;
attribute vec3 aColor;
uniform float uScale;   // pixels per world unit at distance 1
varying float vAlpha;
varying vec3 vColor;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = max(1.5, aSize * uScale / -mv.z);
  vAlpha = aAlpha;
  vColor = aColor;
  gl_Position = projectionMatrix * mv;
}
