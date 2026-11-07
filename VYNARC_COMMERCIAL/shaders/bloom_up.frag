// 9-tap tent upsample of the lower mip, added to the current level.
uniform sampler2D tLow;
uniform sampler2D tCur;
uniform vec2 uTexel;   // texel of tLow
uniform float uRadius;
uniform float uCurWeight;
varying vec2 vUv;
vec3 tap(vec2 o) { return texture(tLow, vUv + o * uTexel * uRadius).rgb; }
void main() {
  vec3 c = tap(vec2(0)) * 4.0;
  c += (tap(vec2(-1,0)) + tap(vec2(1,0)) + tap(vec2(0,-1)) + tap(vec2(0,1))) * 2.0;
  c += tap(vec2(-1,-1)) + tap(vec2(1,-1)) + tap(vec2(-1,1)) + tap(vec2(1,1));
  c /= 16.0;
  gl_FragColor = vec4(c + texture(tCur, vUv).rgb * uCurWeight, 1.0);
}
