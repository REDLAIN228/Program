// 00:00–00:02 THE ORIGIN
// Black void -> faint violet breath -> a thin line of light rises from depth
// along the frame diagonal, thickens into a twisting 3D ribbon with silver
// sheen and, with physical inertia (damped spring), settles into the exact
// orbit arc of the official symbol.
import * as THREE from 'three';
import { Ribbon, Glow, BRAND } from './lib.js';
import { seg, ease, clamp, lerp, window4, spring } from '../animations/easing.js';

export function cameraKeys(ctx) {
  const d = ctx.portrait ? 1.08 : 1.0;
  //  t,    px,   py,   pz,       tx,   ty,   tz,  roll
  return [
    [0.0, 0.9, 0.55, 15.5 * d, 0.0, 0.05, -3.0, 0.02],
    [1.0, 0.65, 0.4, 12.2 * d, 0.0, 0.08, -1.5, 0.015],
    [2.0, 0.25, 0.2, 9.0 * d, 0.05, 0.12, 0.0, 0.0],
  ];
}

const bez = (a, b, c, d, u, out) => {
  const iu = 1 - u;
  return out.set(
    iu * iu * iu * a[0] + 3 * iu * iu * u * b[0] + 3 * iu * u * u * c[0] + u * u * u * d[0],
    iu * iu * iu * a[1] + 3 * iu * iu * u * b[1] + 3 * iu * u * u * c[1] + u * u * u * d[1],
    iu * iu * iu * a[2] + 3 * iu * iu * u * b[2] + 3 * iu * u * u * c[2] + u * u * u * d[2],
  );
};

export function create(ctx) {
  const { S, scene } = ctx;
  const group = new THREE.Group();
  scene.add(group);
  const o = ctx.geo.orbit;
  const ratio = o.b / o.a;
  const U = new THREE.Vector3(o.u[0], o.u[1], 0);
  const Wv = new THREE.Vector3(o.u[1], -o.u[0], 0).multiplyScalar(ratio).add(new THREE.Vector3(0, 0, -Math.sqrt(1 - ratio * ratio)));
  const C = new THREE.Vector3(o.center[0], o.center[1], 0.2);
  const arcAt = (s) => {
    const th = lerp(o.theta_tail - 0.04, o.theta_head + 0.02, s);
    return C.clone().addScaledVector(U, o.a * Math.cos(th)).addScaledVector(Wv, o.a * Math.sin(th));
  };
  const P = ctx.portrait ? 0.62 : 1.0; // narrower sweep for 9:16

  const main = new Ribbon(S, { segments: 280 });
  group.add(main.mesh);
  const silkA = new Ribbon(S, { segments: 160, core: BRAND.violet, glow: BRAND.deep });
  const silkB = new Ribbon(S, { segments: 160, core: BRAND.neon, glow: BRAND.deep });
  group.add(silkA.mesh, silkB.mesh);
  const breath = new Glow(S, BRAND.deep, 30, 2.4);
  breath.mesh.position.set(0, -0.5, -16);
  group.add(breath.mesh);
  const v = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0.35).normalize();

  return {
    update(t) {
      const vis = t < 2.35;
      group.visible = vis;
      if (!vis) return;
      breath.face(ctx.camera);
      breath.mat.uniforms.uIntensity.value = 0.08 * seg(t, 0.05, 1.1, ease.inOut) * (0.9 + 0.1 * Math.sin(t * 3.1)) * (1 - seg(t, 1.8, 2.3));

      // free flight: from deep lower-left, across the diagonal, toward camera
      const w1 = 0.7 * Math.sin(t * 1.1), w2 = 0.5 * Math.cos(t * 0.8);
      const A = [-7.5 * P, -4.2, -26], B = [-3.2 * P, -2.6 + w1, -9], Cc = [2.6 * P, 0.6 + w2, -2.5], D = [6.0 * P, 3.3, 3.5];
      const m = clamp(spring(t, 1.0, 5.0, 0.86));   // inertia of the "landing" into the arc
      main.update(
        (u) => {
          const f = bez(A, B, Cc, D, u, v).clone();
          // ribbon bends into the arc from its head first, the tail follows
          const mu = clamp(m * 1.3 - (1 - u) * 0.3);
          return f.lerp(arcAt(u), mu * mu * (3 - 2 * mu));
        },
        (u) => {
          const swell = lerp(0.015, 0.5, seg(t, 0.55, 1.25, ease.out));
          const settle = lerp(swell, o.max_thickness * 0.5 * (0.12 + 0.88 * Math.pow(u, 1.6)), m);
          return settle * (0.25 + 0.75 * Math.sin(Math.PI * clamp(u * 1.04)));
        },
        (u) => (1 - m) * (1.25 * Math.sin(u * 3.6 - t * 1.7) + 0.35),
        up,
      );
      const mu = main.mat.uniforms;
      mu.uTime.value = t;
      mu.uHead.value = lerp(-0.04, 1.12, seg(t, 0.32, 1.45, ease.cine));
      mu.uTail.value = -0.3;
      mu.uHeadGlow.value = window4(t, 0.35, 0.5, 1.25, 1.55);
      mu.uIntensity.value = 1.45 * seg(t, 0.3, 0.55, ease.out) * (1 - seg(t, 1.95, 2.3, ease.inOut));
      mu.uCoreOffset.value = lerp(0.55, 0.0, m);
      mu.uCoreWidth.value = lerp(0.09, 0.6, m);
      mu.uSoftness.value = lerp(1.7, 6.0, m);
      mu.uBodyAmt.value = lerp(0.85, 0.25, m);
      mu.uSilverAmt.value = 1.1 * (1 - m * 0.8);

      // background silk: wide, slow, diagonal soft light (no hard edges)
      const silk = (rib, phase, z, amp, inten) => {
        rib.update(
          (u) => v.set(lerp(-18, 18, u) * P, lerp(-9, 9, u) * 0.62 + amp * Math.sin(u * 2.4 + t * 0.45 + phase), z + 2.5 * Math.sin(u * 2.8 + phase)).clone(),
          (u) => 3.2 * Math.sin(Math.PI * u),
          (u) => 0.5 * Math.sin(u * 2.0 + t * 0.5 + phase) + 0.25,
          new THREE.Vector3(0, 0, 1),
        );
        const su = rib.mat.uniforms;
        su.uTime.value = t;
        su.uHead.value = 1.2; su.uTail.value = -0.3; su.uHeadGlow.value = 0;
        su.uCoreOffset.value = 0.62; su.uCoreWidth.value = 0.16; su.uSoftness.value = 1.25;
        su.uBodyAmt.value = 0.5; su.uSilverAmt.value = 0.0;
        su.uIntensity.value = inten * window4(t, 0.45, 1.3, 1.5, 2.25);
      };
      silk(silkA, 0.0, -15, 1.6, 0.42);
      silk(silkB, 2.3, -21, 2.2, 0.22);
    },
  };
}
