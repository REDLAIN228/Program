// 13-tap "COD" downsample (energy preserving, no fireflies).
uniform sampler2D tSrc;
uniform vec2 uTexel;
varying vec2 vUv;
vec3 tap(vec2 o) { return texture(tSrc, vUv + o * uTexel).rgb; }
void main() {
  vec3 c = tap(vec2(0)) * 0.125;
  c += (tap(vec2(-1,-1)) + tap(vec2(1,-1)) + tap(vec2(-1,1)) + tap(vec2(1,1))) * 0.125;
  c += (tap(vec2(-2,-2)) + tap(vec2(2,-2)) + tap(vec2(-2,2)) + tap(vec2(2,2))) * 0.03125;
  c += (tap(vec2(-2,0)) + tap(vec2(2,0)) + tap(vec2(0,-2)) + tap(vec2(0,2))) * 0.0625;
  gl_FragColor = vec4(c, 1.0);
}
