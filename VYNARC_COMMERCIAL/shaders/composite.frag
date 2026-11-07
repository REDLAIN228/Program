// Final grade: bloom + streaks, hue-preserving filmic shoulder, brand black
// lift (#05030B), vignette, minimal chromatic aberration, film grain, dither.
uniform sampler2D tScene;
uniform sampler2D tBloom;
uniform sampler2D tStreak;
uniform vec2 uRes;
uniform float uBloom;
uniform float uStreak;
uniform float uExposure;
uniform float uFrame;
uniform float uGrain;
uniform float uVignette;
uniform float uCA;
uniform float uFade;      // 1 = full image, 0 = black
uniform float uLift;      // 1 = brand black floor, 0 = pure black
uniform vec3 uBlack;      // linear brand background
uniform vec3 uStreakTint;
varying vec2 vUv;

float hash(vec2 p) {
  p = fract(p * vec2(443.897, 441.423));
  p += dot(p, p.yx + 19.19);
  return fract((p.x + p.y) * p.x);
}

vec3 shoulder(vec3 c) {
  // Identity up to k, smooth exponential shoulder above -> UI stays faithful,
  // light sources roll off; very hot cores bleach towards white like film.
  float k = 0.72;
  float peak = max(c.r, max(c.g, c.b));
  if (peak <= k) return c;
  float mapped = k + (1.0 - k) * (1.0 - exp(-(peak - k) / (1.0 - k)));
  vec3 hue = c / peak;
  float bleach = smoothstep(1.2, 6.0, peak);
  return mix(hue, vec3(1.0), bleach * 0.85) * mapped;
}

vec3 toSRGB(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

void main() {
  vec2 d = vUv - 0.5;
  float r2 = dot(d * vec2(uRes.x / uRes.y, 1.0), d * vec2(uRes.x / uRes.y, 1.0));
  vec2 ca = d * uCA * r2;
  vec3 c;
  c.r = texture(tScene, vUv - ca).r;
  c.g = texture(tScene, vUv).g;
  c.b = texture(tScene, vUv + ca).b;
  c += texture(tBloom, vUv).rgb * uBloom;
  c += texture(tStreak, vUv).rgb * uStreak * uStreakTint;
  c *= uExposure;
  c = shoulder(c);
  // vignette (elliptical, soft)
  float vig = smoothstep(1.55, 0.35, length(d * 2.0 * vec2(1.0, 0.86)));
  c *= mix(1.0, vig, uVignette);
  c *= uFade;
  // brand black floor
  c = uBlack * uLift + c * (1.0 - uBlack * uLift);
  vec3 s = toSRGB(c);
  // luminance-weighted film grain (stronger in mids), animated per frame
  vec2 px = vUv * uRes;
  float g = hash(px + fract(uFrame * 0.61803) * 1000.0) + hash(px * 1.37 + fract(uFrame * 0.4142) * 777.0) - 1.0;
  float lum = dot(s, vec3(0.299, 0.587, 0.114));
  s += g * uGrain * (0.35 + 0.65 * smoothstep(0.0, 0.35, lum) * (1.0 - smoothstep(0.6, 1.0, lum)));
  // triangular dither against 8-bit banding in the dark violet gradients
  s += (hash(px * 0.917 + uFrame) + hash(px * 1.731 - uFrame) - 1.0) / 255.0;
  gl_FragColor = vec4(s, 1.0);
}
