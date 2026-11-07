// Motion-blur accumulation: each sub-frame is added with weight 1/K.
uniform sampler2D tSrc;
uniform float uWeight;
varying vec2 vUv;
void main() { gl_FragColor = vec4(texture(tSrc, vUv).rgb * uWeight, 1.0); }
