// Soft-knee bright pass, 13-tap downsample at the same time (half res).
uniform sampler2D tSrc;
uniform vec2 uTexel;      // texel of the source
uniform float uThreshold; // linear HDR
uniform float uKnee;
varying vec2 vUv;
vec3 tap(vec2 o) { return texture(tSrc, vUv + o * uTexel).rgb; }
void main() {
  vec3 c = tap(vec2(0)) * 0.125;
  c += (tap(vec2(-1,-1)) + tap(vec2(1,-1)) + tap(vec2(-1,1)) + tap(vec2(1,1))) * 0.125;
  c += (tap(vec2(-2,-2)) + tap(vec2(2,-2)) + tap(vec2(-2,2)) + tap(vec2(2,2))) * 0.03125;
  c += (tap(vec2(-2,0)) + tap(vec2(2,0)) + tap(vec2(0,-2)) + tap(vec2(0,2))) * 0.0625;
  float br = max(c.r, max(c.g, c.b));
  float soft = clamp(br - uThreshold + uKnee, 0.0, 2.0 * uKnee);
  soft = soft * soft / (4.0 * uKnee + 1e-4);
  float contrib = max(soft, br - uThreshold) / max(br, 1e-4);
  gl_FragColor = vec4(c * contrib, 1.0);
}
