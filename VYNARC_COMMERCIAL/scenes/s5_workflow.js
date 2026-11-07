// 00:10–00:12 LIMITLESS WORKFLOW
// Camera pulls back; the interface components detach and re-assemble into one
// 3D structure — a tilted orbit (the logo's own arc motif) around the hub,
// stitched by connections. Then, one after another, they dissolve into a
// restrained stream of violet light particles.
import * as THREE from 'three';
import { Panel, Line, Glow, Text, Particles, BRAND, lin } from './lib.js';
import { HUB } from './s2_brand.js';
import { animateCaption } from './s3_connect.js';
import { seg, ease, clamp, lerp, window4, spring, drift, hash1 } from '../animations/easing.js';

const RING = ['hero', 'assistant', 'pc2', 'map', 'recent', 'pc4', 'activity', 'quick', 'pc1', 'templates', 'pc3', 'projects'];
const RING_P = ['hero', 'assistant', 'pc2', 'map', 'recent', 'pc4', 'activity', 'pc1', 'pc3', 'projects'];

export function cameraKeys(ctx) {
  const H = HUB;
  const d = ctx.portrait ? 1.0 : ctx.square ? 1.12 : 1.0;
  return [
    [10.0, ctx.square ? 0.75 : ctx.portrait ? -0.42 : -0.65, -0.1, H.z + 4.0, ctx.square ? 0.6 : -0.05, -0.05, H.z, 0.0],
    [10.55, -0.4, 0.45, H.z + 7.6 * d, -0.05, 0.05, H.z, 0.01],
    [11.2, -0.4, 0.9, H.z + 9.6 * d, 0.0, 0.0, H.z, 0.02],
    [11.99, 1.1, 0.8, H.z + 10.6 * d, 0.1, 0.0, H.z, -0.01],
  ];
}

export function create(ctx) {
  const { S, scene, overlay, tex } = ctx;
  const U = ctx.reg.universe;
  const names = (ctx.portrait ? RING_P : RING).filter((n) => U.parts[n]);
  const N = names.length;
  const tilt = 1.08;
  const Rx = ctx.portrait ? 2.0 : ctx.square ? 2.9 : 3.4, Ry = ctx.portrait ? 3.4 : 2.2;
  const slotOf = (i, t) => {
    const a = (i / N) * Math.PI * 2 + 0.35 + t * 0.12;      // the structure slowly rotates
    return new THREE.Vector3(Rx * Math.cos(a), Ry * Math.sin(a) * Math.cos(tilt) + 0.15 * Math.sin(a * 2), Ry * Math.sin(a) * Math.sin(tilt) * 0.9);
  };
  const targetW = ctx.portrait ? 1.35 : 1.6;

  const hub = new Panel(S, tex.hub, 1.7, { shadow: false, rim: 0 });
  hub.group.position.copy(HUB);
  scene.add(hub.group);
  const hubGlow = new Glow(S, BRAND.violet, 6, 3.0);
  hubGlow.mesh.position.copy(HUB);
  scene.add(hubGlow.mesh);
  const lines = names.map(() => { const l = new Line(S, { width: 0.016 }); scene.add(l.mesh); return l; });
  const ring = names.map(() => { const l = new Line(S, { width: 0.01, color: BRAND.violet }); scene.add(l.mesh); return l; });

  // particles: each panel releases a share when its dissolve front passes
  const PER = 520;
  const parts = new Particles(S, N * PER + 600);
  scene.add(parts.points);
  const cNeon = lin(BRAND.neon), cDeep = lin(BRAND.violet), cSil = lin(BRAND.silver);

  const cap = new Text(S, 'CREATE WITHOUT LIMITS.', { size: ctx.portrait ? 0.07 : 0.085, weight: 600, tracking: 0.2 });
  cap.group.scale.setScalar(Math.min(1, (ctx.aspect * 2 * 0.86) / cap.width));
  cap.group.position.set(0, ctx.portrait ? -0.8 : -0.74, 0);
  overlay.add(cap.group);

  const tmpM = new THREE.Matrix4();
  const camPos = new THREE.Vector3();
  const local = new THREE.Vector3();

  return {
    update(t) {
      const vis = t >= 10.0 && t < 12.3;
      hub.group.visible = vis; hubGlow.mesh.visible = vis; parts.points.visible = vis;
      lines.forEach((l) => (l.mesh.visible = vis)); ring.forEach((l) => (l.mesh.visible = vis));
      cap.group.visible = t > 10.6 && t < 12.0;
      if (cap.group.visible) animateCaption(cap, t, 10.75, 11.55, 11.9);
      if (!vis) return;
      U.group.visible = true;
      camPos.copy(ctx.camera.position);
      // the dashboard group straightens while the structure forms
      const g = U.group;
      g.rotation.y = lerp(-0.08 * (ctx.portrait ? 0.6 : 1), 0, seg(t, 10.0, 10.6));
      g.rotation.x = lerp(0.03, 0, seg(t, 10.0, 10.6));
      g.updateMatrixWorld();
      if (U.base) {
        U.base.opacity = 0.9 * (1 - seg(t, 10.0, 10.35, ease.inOut));
        U.base.mat.uniforms.uBias.value = 3 * seg(t, 10.0, 10.35);
      }
      for (const n of ['sidebar', 'topbar']) {
        const p = U.parts[n];
        if (!p) continue;
        p.opacity = 1 - seg(t, 10.0, 10.3, ease.inOut);
        p.group.position.z = p.slot.z - 0.6 * seg(t, 10.0, 10.3, ease.in);
      }
      const pv = U.preview;
      pv.opacity = 1 - seg(t, 10.0, 10.25);
      pv.group.position.z += 0.0;

      const hubIn = seg(t, 10.25, 10.7, ease.out);
      hub.group.quaternion.copy(ctx.camera.quaternion);
      hub.group.scale.setScalar(lerp(0.5, 1, hubIn));
      hub.opacity = hubIn * (1 - seg(t, 11.75, 12.05));
      hub.mat.uniforms.uDissolve.value = seg(t, 11.7, 12.1);
      hubGlow.face(ctx.camera);
      hubGlow.mat.uniforms.uIntensity.value = 0.1 * hubIn * (1 - seg(t, 11.7, 12.1));

      let pi = 0;
      names.forEach((n, i) => {
        const p = U.parts[n];
        const k = clamp(spring(t, 10.08 + i * 0.04, 6.8, 0.84));
        const slot = slotOf(i, t - 10.0);
        // slot is in world space around the hub -> convert into the group's local space
        const world = slot.clone().add(HUB);
        local.copy(world);
        g.worldToLocal(local);
        p.group.position.copy(p.slot).lerp(local, k);
        p.group.position.y += 0.05 * drift(t, i + 3, 1, 0.6) * k;
        const sc = lerp(1, Math.min(1.6, targetW / p.w), k);
        p.group.scale.setScalar(sc);
        // face the camera progressively (keeps each component readable)
        p.group.quaternion.identity().slerp(ctx.camera.quaternion, 0.6 * k);
        p.group.rotateY(0.15 * Math.sin(i * 1.7) * k);
        const d0 = 11.15 + i * 0.07;
        const dis = seg(t, d0, d0 + 0.5, ease.inSoft);
        p.mat.uniforms.uDissolve.value = dis;
        p.mat.uniforms.uBias.value = 0;
        p.mat.uniforms.uBright.value = 1;
        p.mat.uniforms.uRim.value = 0.1 + 0.4 * window4(t, 10.3 + i * 0.04, 10.5, 10.9, 11.2);
        p.mat.uniforms.uSheen.value = lerp(-0.6, 1.9, seg(t, 10.6 + i * 0.05, 11.3 + i * 0.05, ease.inOut));
        p.opacity = 1;

        // connections hub->panel and ring neighbours, following the motion
        const wp = new THREE.Vector3(); p.group.getWorldPosition(wp);
        const l = lines[i];
        l.update(HUB.clone().add(wp.clone().sub(HUB).normalize().multiplyScalar(0.7)), wp.clone().lerp(HUB, 0.12), camPos, new THREE.Vector3(0, 0.15, 0.25));
        l.mat.uniforms.uProgress.value = lerp(-0.05, 1.1, seg(t, 10.45 + i * 0.03, 10.95 + i * 0.03, ease.inOut));
        l.mat.uniforms.uIntensity.value = 0.8 * (1 - seg(t, d0, d0 + 0.3));
        l.mat.uniforms.uPulse.value = ((t - 10.6 - i * 0.13) * 0.9) % 1.3;
        l.mat.uniforms.uPulseAmt.value = 0.9;
        const nx = U.parts[names[(i + 1) % N]];
        const wq = new THREE.Vector3(); nx.group.getWorldPosition(wq);
        const r = ring[i];
        r.update(wp, wq, camPos, new THREE.Vector3(0, 0, 0.3));
        r.mat.uniforms.uProgress.value = lerp(-0.05, 1.1, seg(t, 10.6 + i * 0.04, 11.05 + i * 0.04, ease.inOut));
        r.mat.uniforms.uIntensity.value = 0.6 * (1 - seg(t, d0 - 0.1, d0 + 0.25));
        r.mat.uniforms.uPulse.value = -1; r.mat.uniforms.uPulseAmt.value = 0;

        // particles of this panel
        p.group.updateMatrixWorld();
        tmpM.copy(p.mesh.matrixWorld);
        for (let j = 0; j < PER; j++, pi++) {
          const h1 = hash1(pi * 3.1 + 0.7), h2 = hash1(pi * 7.3 + 1.9), h3 = hash1(pi * 1.7 + 5.3), h4 = hash1(pi * 9.1 + 2.2);
          // the dissolve front sweeps right->left (matches the panel shader bias)
          const birth = d0 + 0.42 * (0.25 * h1 + 0.75 * (1 - (h1 * 0.6 + 0.4 * h2))) ;
          const age = t - birth;
          const o = pi * 3;
          if (age < 0 || age > 1.25) { parts.alpha[pi] = 0; parts.pos[o] = 0; parts.pos[o + 1] = 0; parts.pos[o + 2] = -999; continue; }
          local.set((h1 - 0.5) * p.w, (h2 - 0.5) * p.h, 0).applyMatrix4(tmpM);
          const out = local.clone().sub(HUB).normalize();
          const sp = 0.25 + 0.6 * h3;
          const swirl = age * 1.4 + h4 * 6.28;
          parts.pos[o] = local.x + out.x * sp * age + Math.cos(swirl) * 0.12 * age;
          parts.pos[o + 1] = local.y + out.y * sp * age + 0.35 * age * age + Math.sin(swirl) * 0.12 * age;
          parts.pos[o + 2] = local.z + out.z * sp * age + 0.5 * h4 * age;
          const life = Math.min(1, age / 0.08) * Math.pow(1 - age / 1.25, 1.6);
          parts.alpha[pi] = life * (0.55 + 0.45 * h2);
          parts.size[pi] = 0.018 + 0.03 * h3 * h3;
          const c = h4 < 0.12 ? cSil : (h4 < 0.6 ? cNeon : cDeep);
          parts.color.set([c.r * 1.6, c.g * 1.6, c.b * 1.6], o);
        }
      });
      // the hub's own last particles
      for (let j = 0; j < 600; j++, pi++) {
        const h1 = hash1(pi * 3.1 + 0.7), h2 = hash1(pi * 7.3 + 1.9), h3 = hash1(pi * 1.7 + 5.3);
        const age = t - (11.72 + 0.3 * h1);
        const o = pi * 3;
        if (age < 0 || age > 1.0) { parts.alpha[pi] = 0; parts.pos[o + 2] = -999; continue; }
        const a = h2 * 6.283, r = 0.5 * Math.sqrt(h3);
        parts.pos[o] = HUB.x + Math.cos(a) * (r + age * 0.9);
        parts.pos[o + 1] = HUB.y + Math.sin(a) * (r + age * 0.9) + 0.2 * age * age;
        parts.pos[o + 2] = HUB.z + 0.2;
        parts.alpha[pi] = Math.min(1, age / 0.06) * Math.pow(1 - age, 1.5);
        parts.size[pi] = 0.02 + 0.02 * h3;
        parts.color.set([cNeon.r * 1.8, cNeon.g * 1.8, cNeon.b * 1.8], o);
      }
      parts.mat.uniforms.uScale.value = ctx.H / (2 * Math.tan(THREE.MathUtils.degToRad(ctx.camera.fov / 2)));
      parts.commit();
    },
  };
}
