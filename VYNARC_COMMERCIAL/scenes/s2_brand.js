// 00:02–00:04 BRAND MATERIALIZATION
// The ribbon has become the orbit arc. The official V symbol materialises out
// of it in polished metal (traced from the official artwork), a glint runs
// across, the camera orbits, then dives through the gap above the light arc
// into the space behind — where the workspace waits.
import * as THREE from 'three';
import { LogoSymbol3D, Glow, Particles, BRAND, lin } from './lib.js';
import { seg, ease, clamp, lerp, window4, hash1 } from '../animations/easing.js';

export const HUB = new THREE.Vector3(0, 0, -24);

export function cameraKeys(ctx) {
  const d = ctx.portrait ? 1.25 : ctx.square ? 1.08 : 1.0;
  const sph = (az, el, r) => [Math.sin(az) * Math.cos(el) * r, Math.sin(el) * r, Math.cos(az) * Math.cos(el) * r];
  const a = sph(0.18, 0.07, 7.6 * d);
  const b = sph(0.62, -0.02, 6.4 * d);
  //  t,     px,    py,    pz,     tx,   ty,   tz,  roll
  return [
    [2.6, a[0], a[1] + 0.15, a[2], 0.0, 0.1, 0.0, 0.0],
    [3.25, b[0], b[1] + 0.1, b[2], 0.05, 0.15, 0.0, -0.03],
    [3.62, 1.35, 0.72, 2.6, 0.0, 0.62, -1.0, -0.06],
    [3.82, 0.05, 0.64, 0.25, 0.0, 0.55, -8.0, -0.02],
    [4.02, 0.0, 0.55, -4.0, 0.0, 0.2, -24.0, 0.0],
  ];
}

export function create(ctx) {
  const { S, scene, geo, envMap } = ctx;
  const logo = new LogoSymbol3D(S, geo, envMap);
  scene.add(logo.group);
  const halo = new Glow(S, BRAND.violet, 9, 2.6);
  halo.mesh.position.set(0, 0, -1.5);
  scene.add(halo.mesh);
  const flare = new Glow(S, BRAND.neon, 3.2, 5.0);
  scene.add(flare.mesh);
  const head = logo.orbit.at(0.93);
  // light dust along the dive: streaks under motion blur give the speed
  const DUST = 700;
  const dust = new Particles(S, DUST);
  const cN = lin(BRAND.neon), cS = lin(BRAND.silver);
  for (let i = 0; i < DUST; i++) {
    const a = hash1(i * 1.37) * Math.PI * 2, r = 0.6 + 3.2 * Math.sqrt(hash1(i * 2.71 + 4));
    dust.pos.set([Math.cos(a) * r, 0.4 + Math.sin(a) * r * 0.7, lerp(2.5, -23, hash1(i * 5.13 + 1))], i * 3);
    dust.size[i] = 0.01 + 0.018 * hash1(i * 7.7);
    const c = hash1(i * 3.3) < 0.3 ? cS : cN;
    dust.color.set([c.r, c.g, c.b], i * 3);
  }
  scene.add(dust.points);

  return {
    logo,
    update(t) {
      const dv = t > 3.1 && t < 4.9;
      dust.points.visible = dv;
      if (dv) {
        const k = window4(t, 3.2, 3.5, 4.3, 4.85);
        for (let i = 0; i < DUST; i++) dust.alpha[i] = k * (0.35 + 0.65 * hash1(i * 9.1)) * (0.6 + 0.4 * Math.sin(t * 6 + i));
        dust.mat.uniforms.uScale.value = ctx.H / (2 * Math.tan(THREE.MathUtils.degToRad(ctx.camera.fov / 2)));
        dust.commit();
      }
      const vis = t > 1.8 && t < 4.2;
      logo.group.visible = vis; halo.mesh.visible = vis; flare.mesh.visible = vis;
      if (!vis) return;
      halo.face(ctx.camera); flare.face(ctx.camera);
      // arc takes over from the ribbon
      const om = logo.orbit.mat.uniforms;
      om.uIntensity.value = seg(t, 1.85, 2.15, ease.inOut);
      om.uReveal.value = 1.1;
      om.uPulse.value = 0.6 * Math.exp(-Math.pow((t - 2.2) / 0.18, 2)) + 1.6 * seg(t, 3.45, 3.8, ease.in);
      // metal materialisation (noise front, hot violet edge)
      logo.fx.uMat.value = lerp(-0.08, 1.12, seg(t, 2.05, 2.85, ease.outSoft));
      logo.fx.uSweep.value = lerp(-2.6, 2.8, seg(t, 2.55, 3.2, ease.inOut));
      logo.fx.uSweepAmt.value = 0.9 * window4(t, 2.5, 2.65, 3.05, 3.25);
      logo.fx.uGlowAdd.value = 0.05 * seg(t, 2.1, 2.6);
      // a slow weightless turn of the symbol itself, opposing the camera orbit
      logo.group.rotation.y = lerp(-0.12, 0.06, seg(t, 2.0, 3.6, ease.cine));
      logo.group.rotation.x = 0.03 * Math.sin(t * 1.3);
      logo.group.position.y = 0.04 * Math.sin(t * 1.7);
      halo.mat.uniforms.uIntensity.value = 0.035 * seg(t, 2.0, 2.6) * (1 - seg(t, 3.4, 3.8));
      flare.mesh.position.copy(head).applyMatrix4(logo.group.matrixWorld);
      flare.mat.uniforms.uIntensity.value = 0.3 * seg(t, 1.9, 2.2) + 1.6 * seg(t, 3.4, 3.8, ease.in) * (1 - seg(t, 3.85, 4.05));
    },
  };
}
