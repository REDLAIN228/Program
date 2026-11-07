// 00:07–00:10 YOUR CREATIVE UNIVERSE
// The hub opens: the real VYNARC main screen assembles out of it in layered
// depth (each component is its own glass plane). "ONE WORKSPACE." in front of
// a defocused UI, then a focus pull: the interface is readable, project cards
// lift forward one by one, a file preview floats out, the camera turns.
import * as THREE from 'three';
import { Panel, Glow, Text, Line, BRAND } from './lib.js';
import { HUB } from './s2_brand.js';
import { animateCaption } from './s3_connect.js';
import { seg, ease, clamp, lerp, window4, spring, drift } from '../animations/easing.js';

export const PARTS = ['sidebar', 'topbar', 'hero', 'assistant', 'projects', 'pc1', 'pc2', 'pc3', 'pc4', 'activity', 'map', 'recent', 'templates', 'quick'];
const DEPTH = { sidebar: 0.03, topbar: 0.05, hero: 0.09, assistant: 0.12, projects: 0.07, pc1: 0.12, pc2: 0.12, pc3: 0.12, pc4: 0.12, activity: 0.1, map: 0.11, recent: 0.09, templates: 0.08, quick: 0.12 };
// assembly order: from the centre outward
const ORDER = ['projects', 'hero', 'map', 'recent', 'pc2', 'pc3', 'templates', 'pc1', 'pc4', 'assistant', 'activity', 'quick', 'topbar', 'sidebar'];

// Portrait re-composition (virtual 900px-wide canvas). Width per part; the
// height follows each texture's aspect. Same components, stacked for 9:16.
const PORTRAIT = {
  hero: [33, 0, 834], projects: [33, 276, 834], assistant: [33, 473, 412], activity: [457, 473, 410],
  map: [33, 807, 412], recent: [457, 735, 410],
};

export function dashboardSpec(ctx) {
  const L = ctx.layout;
  const DW = 4.3, dw = L.dashboard.w, dh = L.dashboard.h;
  const spec = {};
  if (ctx.portrait) {
    const u = 2.42 / 900;
    const totalH = 1131;
    for (const [name, [x, y, w]] of Object.entries(PORTRAIT)) {
      const p = L.parts[name];
      const h = (w * p.h) / p.w;
      spec[name] = { x: (x + w / 2 - 450) * u, y: -(y + h / 2 - totalH / 2) * u, w: w * u };
    }
    // project cards keep their place inside the projects block
    const pj = L.parts.projects, P = PORTRAIT.projects, s = P[2] / pj.w;
    for (const n of ['pc1', 'pc2', 'pc3', 'pc4']) {
      const p = L.parts[n];
      const x = P[0] + (p.x - pj.x) * s, y = P[1] + (p.y - pj.y) * s, w = p.w * s, h = p.h * s;
      spec[n] = { x: (x + w / 2 - 450) * u, y: -(y + h / 2 - totalH / 2) * u, w: w * u };
    }
    spec._base = null;
    spec._w = 900 * u; spec._h = totalH * u;
  } else {
    for (const name of PARTS) {
      const p = L.parts[name];
      spec[name] = { x: ((p.x + p.w / 2) / dw - 0.5) * DW, y: -((p.y + p.h / 2) / dh - 0.5) * DW * (dh / dw), w: (p.w / dw) * DW };
    }
    spec._base = { w: DW };
    spec._w = DW; spec._h = DW * (dh / dw);
  }
  return spec;
}

export function cameraKeys(ctx) {
  const H = HUB;
  if (ctx.portrait) {
    return [
      [7.45, 0.05, 0.05, H.z + 3.5, 0.0, 0.0, H.z, 0.0],
      [8.0, 0.18, 0.2, H.z + 4.45, 0.0, 0.05, H.z, 0.0],
      [9.0, -0.12, 0.1, H.z + 4.35, 0.0, 0.0, H.z, 0.0],
      [9.95, -0.42, -0.15, H.z + 4.1, -0.05, -0.05, H.z, 0.0],
    ];
  }
  if (ctx.square) {
    return [
      [7.45, 0.1, 0.05, H.z + 3.4, 0.0, 0.0, H.z, 0.0],
      [8.0, -0.55, 0.12, H.z + 3.9, -0.5, 0.08, H.z, 0.0],
      [9.0, 0.05, 0.05, H.z + 3.75, 0.05, 0.0, H.z, 0.0],
      [9.95, 0.75, -0.1, H.z + 3.6, 0.62, -0.05, H.z, 0.0],
    ];
  }
  return [
    [7.45, 0.15, 0.05, H.z + 3.6, 0.0, 0.0, H.z, 0.0],
    [8.0, 0.5, 0.12, H.z + 4.55, 0.05, 0.0, H.z, 0.0],
    [9.0, -0.1, 0.06, H.z + 4.35, 0.0, 0.0, H.z, 0.0],
    [9.95, -0.55, -0.08, H.z + 4.3, -0.05, 0.0, H.z, 0.0],
  ];
}

export function create(ctx) {
  const { S, scene, overlay, tex } = ctx;
  const spec = dashboardSpec(ctx);
  const group = new THREE.Group();
  group.position.copy(HUB);
  scene.add(group);
  let base = null;
  if (spec._base) {
    base = new Panel(S, tex.dashboard_base, spec._base.w, { shadow: false, rim: 0.15 });
    base.mat.uniforms.uSeed.value = 0.5;
    group.add(base.group);
  }
  const parts = {};
  PARTS.forEach((name, i) => {
    if (!spec[name]) return;
    const p = new Panel(S, tex[`part_${name}`], spec[name].w, { radius: 0.03, rim: 0.08, shadow: name !== 'topbar' && name !== 'sidebar' });
    p.mat.uniforms.uSeed.value = 2.0 + i * 1.37;
    p.name = name;
    p.slot = new THREE.Vector3(spec[name].x, spec[name].y, DEPTH[name] ?? 0.08);
    p.order = ORDER.indexOf(name);
    group.add(p.group);
    parts[name] = p;
  });
  // file preview that floats out of "Недавно открытые"
  const preview = new Panel(S, tex.preview, ctx.portrait ? 1.25 : 1.15, { radius: 0.05, rim: 0.45 });
  preview.mat.uniforms.uSeed.value = 9.1;
  group.add(preview.group);
  const flash = new Glow(S, BRAND.violet, 6, 3.5);
  flash.mesh.position.copy(HUB).add(new THREE.Vector3(0, 0, 0.3));
  scene.add(flash.mesh);

  const cap = new Text(S, 'ONE WORKSPACE.', { size: ctx.portrait ? 0.1 : 0.13, weight: 650, tracking: 0.16 });
  cap.group.scale.setScalar(Math.min(1, (ctx.aspect * 2 * 0.86) / cap.width));
  overlay.add(cap.group);

  const pops = { pc1: 8.75, pc2: 8.95, pc3: 9.15, pc4: 9.4 };
  const inst = {
    group, parts, base, preview, spec,
    update(tIn) {
      // after 10.0 scene 5 takes these panels over; we keep evaluating our
      // final state so every frame is a pure function of time
      const t = Math.min(tIn, 9.999);
      const vis = tIn > 6.95 && tIn < 12.3;
      group.visible = vis; flash.mesh.visible = vis && tIn < 10;
      cap.group.visible = t > 7.45 && t < 8.75;
      if (cap.group.visible) animateCaption(cap, t, 7.55, 8.35, 8.7, 0.035);
      if (!vis) return;
      flash.face(ctx.camera);
      flash.mat.uniforms.uIntensity.value = 0.25 * Math.exp(-Math.pow((t - 7.05) / 0.12, 2));
      // the group turns slowly against the camera drift -> physical depth reads
      group.rotation.y = lerp(0.1, -0.08, seg(t, 7.6, 10.0, ease.inOut)) * (ctx.portrait ? 0.6 : 1);
      group.rotation.x = lerp(-0.05, 0.03, seg(t, 7.6, 10.0, ease.inOut));
      const defocus = window4(t, 7.35, 7.6, 8.3, 8.85, ease.inOut);
      const bright = 1 - 0.45 * defocus;
      if (base) {
        const b = seg(t, 7.0, 7.6, ease.out);
        base.group.scale.setScalar(lerp(0.3, 1, b));
        base.opacity = 0.9 * b;
        base.mat.uniforms.uBias.value = 2.5 * defocus;
        base.mat.uniforms.uBright.value = bright;
      }
      for (const p of Object.values(parts)) {
        const t0 = 7.02 + p.order * 0.045;
        const k = clamp(spring(t, t0, 8.0, 0.8));
        const from = new THREE.Vector3(0, 0, -0.15);
        p.group.position.copy(from).lerp(p.slot, k);
        p.group.position.z += 0.04 * drift(t, p.order + 1, 1, 0.5);
        p.group.scale.setScalar(lerp(0.2, 1, clamp(k)));
        const pop = pops[p.name] ? clamp(spring(t, pops[p.name], 9, 0.7)) : 0;
        p.group.position.z += 0.16 * pop;
        p.group.position.y += 0.015 * pop;
        if (pop) p.group.scale.multiplyScalar(1 + 0.05 * pop);
        if (p.name === 'assistant') p.group.position.z += 0.08 * seg(t, 9.0, 9.5, ease.cine);
        p.opacity = seg(t, t0, t0 + 0.2, ease.out);
        p.mat.uniforms.uBias.value = lerp(3.5, 0, seg(t, t0, t0 + 0.4, ease.out)) + 2.6 * defocus;
        p.mat.uniforms.uBright.value = bright;
        p.mat.uniforms.uRim.value = 0.06 + 0.55 * pop * Math.exp(-Math.max(0, t - (pops[p.name] || 0) - 0.15) * 3) + 0.3 * Math.exp(-Math.pow((t - t0 - 0.1) / 0.12, 2));
        p.mat.uniforms.uSheen.value = lerp(-0.6, 1.9, seg(t, 8.7 + p.order * 0.03, 9.6 + p.order * 0.03, ease.inOut));
        p.mat.uniforms.uSheenAmt.value = 0.8;
        p.mat.uniforms.uDissolve.value = 0;
      }
      // preview: lifts out of the 4th row of "Недавно открытые"
      const rc = parts.recent;
      const pv = clamp(spring(t, 9.25, 7.5, 0.78));
      const fromP = rc.slot.clone().add(new THREE.Vector3(-rc.w * 0.1, -rc.h * 0.32, 0.02));
      const toP = ctx.portrait ? new THREE.Vector3(0.45, -0.9, 0.55) : ctx.square ? new THREE.Vector3(0.35, -0.35, 0.55) : new THREE.Vector3(0.98, -0.62, 0.55);
      preview.group.position.copy(fromP).lerp(toP, pv);
      preview.group.scale.setScalar(lerp(0.15, 1, pv));
      preview.group.rotation.set(0.04 * pv, -0.18 * pv, 0.02 * pv);
      preview.opacity = seg(t, 9.25, 9.45);
      preview.mat.uniforms.uBias.value = lerp(2.5, 0, seg(t, 9.25, 9.6));
      preview.mat.uniforms.uSheen.value = lerp(-0.5, 1.8, seg(t, 9.5, 10.0, ease.inOut));
      preview.mat.uniforms.uSheenAmt.value = 1.0;
      preview.mat.uniforms.uDissolve.value = 0;
    },
  };
  ctx.reg = ctx.reg || {};
  ctx.reg.universe = inst;
  return inst;
}
