// Light ribbon: a swept strip; uv.x = along (0..1), uv.y = across (-1..1)
attribute vec3 aNormal;
varying vec2 vUv;
varying vec3 vN;
varying vec3 vV;
varying float vDepth;
void main() {
  vUv = uv;
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vN = normalize(mat3(modelMatrix) * aNormal);
  vV = normalize(cameraPosition - wp.xyz);
  vec4 mv = viewMatrix * wp;
  vDepth = -mv.z;
  gl_Position = projectionMatrix * mv;
}
