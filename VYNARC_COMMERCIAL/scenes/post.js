// HDR post chain: sub-frame accumulation (true motion blur), bloom mip chain,
// anamorphic streaks and the final grade. Everything runs in linear half-float.
import * as THREE from 'three';

export class Post {
  constructor(renderer, W, H, shaders, opts = {}) {
    this.r = renderer;
    this.W = W; this.H = H;
    this.s = shaders;
    const hf = { type: THREE.HalfFloatType, depthBuffer: false, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter };
    this.sceneRT = new THREE.WebGLRenderTarget(W, H, {
      type: THREE.HalfFloatType, samples: opts.msaa ?? 4, depthBuffer: true,
      minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
    });
    this.accumRT = new THREE.WebGLRenderTarget(W, H, hf);
    this.levels = [];
    let w = W, h = H;
    for (let i = 0; i < (opts.bloomLevels ?? 7); i++) {
      w = Math.max(2, Math.round(w / 2)); h = Math.max(2, Math.round(h / 2));
      this.levels.push({ down: new THREE.WebGLRenderTarget(w, h, hf), up: new THREE.WebGLRenderTarget(w, h, hf), w, h });
    }
    const sl = this.levels[2];
    this.streakA = new THREE.WebGLRenderTarget(sl.w, Math.max(2, Math.round(sl.h / 2)), hf);
    this.streakB = this.streakA.clone();

    this.cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const tri = new THREE.BufferGeometry();
    tri.setAttribute('position', new THREE.Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3));
    tri.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 2, 0, 0, 2], 2));
    this.quad = new THREE.Mesh(tri);
    this.quad.frustumCulled = false;
    this.qscene = new THREE.Scene();
    this.qscene.add(this.quad);

    const mk = (frag, uniforms, extra = {}) => new THREE.ShaderMaterial({
      vertexShader: shaders['fullscreen.vert'], fragmentShader: shaders[frag], uniforms,
      depthTest: false, depthWrite: false, ...extra,
    });
    this.mAccum = mk('accum.frag', { tSrc: { value: null }, uWeight: { value: 1 } },
      { blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor, transparent: true });
    this.mThresh = mk('bloom_threshold.frag', { tSrc: { value: null }, uTexel: { value: new THREE.Vector2() }, uThreshold: { value: 0.9 }, uKnee: { value: 0.5 } });
    this.mDown = mk('bloom_down.frag', { tSrc: { value: null }, uTexel: { value: new THREE.Vector2() } });
    this.mUp = mk('bloom_up.frag', { tLow: { value: null }, tCur: { value: null }, uTexel: { value: new THREE.Vector2() }, uRadius: { value: 1 }, uCurWeight: { value: 1 } });
    this.mStreak = mk('streak.frag', { tSrc: { value: null }, uTexel: { value: new THREE.Vector2() }, uStep: { value: 1 } });
    this.mComp = mk('composite.frag', {
      tScene: { value: null }, tBloom: { value: null }, tStreak: { value: null },
      uRes: { value: new THREE.Vector2(W, H) }, uBloom: { value: 0.9 }, uStreak: { value: 0.35 },
      uExposure: { value: 1 }, uFrame: { value: 0 }, uGrain: { value: 0.022 }, uVignette: { value: 0.55 },
      uCA: { value: 0.0025 }, uFade: { value: 1 }, uLift: { value: 1 },
      uBlack: { value: new THREE.Color('#05030B') },
      uStreakTint: { value: new THREE.Color('#B45CFF') },
    });
  }

  pass(mat, target, clear = true) {
    this.quad.material = mat;
    this.r.setRenderTarget(target);
    if (clear) this.r.clear();
    this.r.render(this.qscene, this.cam);
  }

  // renderSub(i) draws sub-frame i of K into sceneRT
  render(K, renderSub, grade) {
    const r = this.r;
    let src;
    if (K <= 1) {
      r.setRenderTarget(this.sceneRT);
      renderSub(0);
      src = this.sceneRT.texture;
    } else {
      r.setRenderTarget(this.accumRT);
      r.setClearColor(0x000000, 1);
      r.clear();
      for (let i = 0; i < K; i++) {
        r.setRenderTarget(this.sceneRT);
        renderSub(i);
        this.mAccum.uniforms.tSrc.value = this.sceneRT.texture;
        this.mAccum.uniforms.uWeight.value = 1 / K;
        this.pass(this.mAccum, this.accumRT, false);
      }
      src = this.accumRT.texture;
    }
    // bloom
    const L = this.levels;
    this.mThresh.uniforms.tSrc.value = src;
    this.mThresh.uniforms.uTexel.value.set(1 / this.W, 1 / this.H);
    this.mThresh.uniforms.uThreshold.value = grade.bloomThreshold ?? 0.85;
    this.mThresh.uniforms.uKnee.value = grade.bloomKnee ?? 0.45;
    this.pass(this.mThresh, L[0].down);
    for (let i = 1; i < L.length; i++) {
      this.mDown.uniforms.tSrc.value = L[i - 1].down.texture;
      this.mDown.uniforms.uTexel.value.set(1 / L[i - 1].w, 1 / L[i - 1].h);
      this.pass(this.mDown, L[i].down);
    }
    let low = L[L.length - 1].down;
    for (let i = L.length - 2; i >= 0; i--) {
      this.mUp.uniforms.tLow.value = low.texture;
      this.mUp.uniforms.tCur.value = L[i].down.texture;
      this.mUp.uniforms.uTexel.value.set(1 / L[i + 1].w, 1 / L[i + 1].h);
      this.mUp.uniforms.uRadius.value = 1.0;
      this.mUp.uniforms.uCurWeight.value = 1.0;
      this.pass(this.mUp, L[i].up);
      low = L[i].up;
    }
    // streaks from level-2 bright pass
    const sA = this.streakA, sB = this.streakB;
    this.mStreak.uniforms.tSrc.value = L[2].down.texture;
    this.mStreak.uniforms.uTexel.value.set(1 / sA.width, 1 / sA.height);
    this.mStreak.uniforms.uStep.value = 1.5;
    this.pass(this.mStreak, sA);
    this.mStreak.uniforms.tSrc.value = sA.texture; this.mStreak.uniforms.uStep.value = 5.0;
    this.pass(this.mStreak, sB);
    this.mStreak.uniforms.tSrc.value = sB.texture; this.mStreak.uniforms.uStep.value = 14.0;
    this.pass(this.mStreak, sA);

    const u = this.mComp.uniforms;
    u.tScene.value = src;
    u.tBloom.value = L[0].up.texture;
    u.tStreak.value = sA.texture;
    u.uBloom.value = (grade.bloom ?? 0.9) / L.length;
    u.uStreak.value = grade.streak ?? 0.3;
    u.uExposure.value = grade.exposure ?? 1;
    u.uFrame.value = grade.frame ?? 0;
    u.uGrain.value = grade.grain ?? 0.02;
    u.uVignette.value = grade.vignette ?? 0.5;
    u.uCA.value = grade.ca ?? 0.002;
    u.uFade.value = grade.fade ?? 1;
    u.uLift.value = grade.lift ?? 1;
    this.pass(this.mComp, null);
  }
}
