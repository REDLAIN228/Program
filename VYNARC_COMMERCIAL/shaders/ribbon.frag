// Volumetric-looking light ribbon: gaussian soft body + bright edge core +
// silver metallic sheen where the strip turns toward the camera.
uniform vec3 uCore;      // neon violet
uniform vec3 uGlow;      // deep violet body
uniform vec3 uSilver;    // silver metal
uniform float uIntensity;
uniform float uHead;     // draw-on head position along u
uniform float uTail;     // erased tail position along u
uniform float uHeadGlow;
uniform float uCoreOffset;
uniform float uCoreWidth;
uniform float uSoftness;
uniform float uSilverAmt;
uniform float uBodyAmt;
uniform float uTime;
varying vec2 vUv;
varying vec3 vN;
varying vec3 vV;
varying float vDepth;
void main() {
  float u = vUv.x, v = vUv.y;
  float along = smoothstep(uHead + 0.002, uHead - 0.05, u) * smoothstep(uTail, uTail + 0.14, u);
  float ends = smoothstep(0.0, 0.06, u) * smoothstep(1.0, 0.94, u);
  float soft = exp(-v * v * uSoftness);
  float dv = (v - uCoreOffset) / uCoreWidth;
  float core = exp(-dv * dv);
  float facing = abs(dot(normalize(vN), normalize(vV)));
  float grazing = 1.0 - facing;
  // silver sheen: metal-like highlight band that rolls across as the strip twists
  float band = exp(-pow((v + 0.35 - 0.5 * sin(u * 9.0 + uTime * 0.8)) / 0.45, 2.0));
  float sheen = pow(facing, 5.0) * band;
  // light ribbons look denser at grazing angles (more glowing volume along view ray)
  float vol = mix(0.55, 1.25, grazing);
  vec3 col = uGlow * soft * uBodyAmt * vol
           + uCore * core * (1.2 + 0.8 * grazing)
           + uSilver * sheen * uSilverAmt;
  // shimmer along the strip
  col *= 0.85 + 0.15 * sin(u * 40.0 - uTime * 3.0 + v * 2.0);
  col *= along * ends * uIntensity;
  float hd = (u - uHead) / 0.012;
  col += mix(uCore, vec3(1.0), 0.5) * exp(-hd * hd) * exp(-v * v * 3.0) * 4.0 * uHeadGlow * step(uTail, u);
  gl_FragColor = vec4(col, 1.0);
}
