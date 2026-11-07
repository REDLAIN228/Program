// 00:04–00:07 CONNECT EVERYTHING
// Glass cards with real VYNARC content (Проекты, Файлы, Заметки, Референсы,
// Связи) are born from the hub and float weightlessly around it. Violet
// connections draw themselves and follow the drifting cards. Camera orbits,
// "EVERYTHING CONNECTED." — then a sharp push into the central hub.
import * as THREE from 'three';
import { Panel, Line, Glow, Text, BRAND } from './lib.js';
import { HUB } from './s2_brand.js';
import { seg, ease, clamp, lerp, window4, spring, drift } from '../animations/easing.js';

const CARDS = [
  { key: 'nc_projects', at: 4.35, L: [-4.5, 1.45, 0.4], P: [-1.85, 1.75, 0.4], S: [-3.2, 1.6, 0.3] },
  { key: 'nc_files', at: 4.5, L: [-4.1, -1.85, -0.6], P: [-1.85, -3.0, -0.5], S: [-3.0, -1.95, -0.5] },
  { key: 'nc_notes', at: 4.65, L: [4.4, 1.7, -0.5], P: [1.85, 1.35, -0.5], S: [3.1, 1.75, -0.5] },
  { key: 'nc_refs', at: 4.8, L: [4.7, -1.55, 0.3], P: [1.85, -3.55, 0.3], S: [3.25, -1.7, 0.3] },
  { key: 'nc_links', at: 4.95, L: [0.3, 2.85, -1.4], P: [0.0, 3.85, -1.2], S: [0.1, 3.05, -1.3] },
];

export function cameraKeys(ctx) {
  const H = HUB;
  const d = ctx.portrait ? 1.0 : ctx.square ? 1.18 : 1.0;
  return [
    [4.45, -1.1, 0.75, H.z + 15.5 * d, -0.2, 0.1, H.z, 0.0],
    [5.4, -2.6, 0.85, H.z + 12.6 * d, -0.1, 0.1, H.z, 0.02],
    [6.35, 2.2, -0.45, H.z + 11.9 * d, 0.1, 0.0, H.z, -0.015],
    [6.72, 0.9, -0.15, H.z + 7.4 * d, 0.03, 0.0, H.z, 0.0],
    [7.0, 0.0, 0.0, H.z + 2.35, 0.0, 0.0, H.z, 0.0],
  ];
}

export function create(ctx) {
  const { S, scene, overlay, tex } = ctx;
  const group = new THREE.Group();
  scene.add(group);
  const hubPanel = new Panel(S, tex.hub, 2.0, { shadow: false, rim: 0 });
  hubPanel.group.position.copy(HUB);
  group.add(hubPanel.group);
  const hubGlow = new Glow(S, BRAND.violet, 7, 3.0);
  hubGlow.mesh.position.copy(HUB).add(new THREE.Vector3(0, 0, -0.3));
  group.add(hubGlow.mesh);
  const layoutKey = ctx.portrait ? 'P' : ctx.square ? 'S' : 'L';
  const cards = CARDS.map((c, i) => {
    const p = new Panel(S, tex[c.key], ctx.portrait ? 2.35 : 2.6, { radius: 0.12 });
    p.mat.uniforms.uSeed.value = i * 3.7 + 1.0;
    group.add(p.group);
    const slot = new THREE.Vector3(...c[layoutKey]).add(HUB);
    return { ...c, panel: p, slot, i };
  });
  // hub spokes + a few card-to-card links
  const spokes = cards.map(() => { const l = new Line(S, { width: 0.022 }); group.add(l.mesh); return l; });
  const PAIRS = [[0, 1], [2, 3], [4, 0], [4, 2]];
  const links = PAIRS.map(() => { const l = new Line(S, { width: 0.012, color: BRAND.violet }); group.add(l.mesh); return l; });

  // caption
  const cap = new Text(S, 'EVERYTHING CONNECTED.', { size: ctx.portrait ? 0.072 : 0.085, weight: 600, tracking: 0.2 });
  const capScale = Math.min(1, (ctx.aspect * 2 * 0.86) / cap.width);
  cap.group.scale.setScalar(capScale);
  cap.group.position.set(0, ctx.portrait ? -0.78 : -0.74, 0);
  overlay.add(cap.group);

  const camPos = new THREE.Vector3();
  const q = new THREE.Quaternion();
  const anchor = (card, toward) => {
    // point on the card's edge facing the target
    const c = card.panel.group.position;
    const dir = toward.clone().sub(c);
    const sx = (card.panel.w * 0.5 * card.panel.group.scale.x) / Math.max(1e-4, Math.abs(dir.x));
    const sy = (card.panel.h * 0.5 * card.panel.group.scale.y) / Math.max(1e-4, Math.abs(dir.y));
    return c.clone().addScaledVector(dir, Math.min(sx, sy, 1));
  };

  return {
    cards, hubPanel, group,
    update(t) {
      const vis = t > 3.6 && t < 7.25;
      group.visible = vis;
      cap.group.visible = t > 5.3 && t < 6.7;
      if (vis) {
        camPos.copy(ctx.camera.position);
        // hub: born from the fly-through light
        const hb = seg(t, 3.62, 4.25, ease.out);
        // at 7.0 the hub "opens": it expands past the camera and dissolves into light
        const open = seg(t, 6.98, 7.3, ease.in);
        hubPanel.group.scale.setScalar(lerp(0.4, 1.0, hb) * (1 + 0.03 * Math.sin(t * 2.2)) * (1 + 2.2 * open));
        hubPanel.opacity = hb * (1 - open) * (1 - open);
        hubPanel.mat.uniforms.uBright.value = 1.0 + 0.9 * Math.exp(-Math.pow((t - 3.95) / 0.2, 2)) + 0.2 * seg(t, 6.6, 7.0, ease.in);
        hubPanel.group.quaternion.copy(ctx.camera.quaternion);
        hubGlow.face(ctx.camera);
        hubGlow.mat.uniforms.uIntensity.value = 0.1 * hb + 0.22 * seg(t, 6.6, 7.0, ease.in) * (1 - seg(t, 7.0, 7.25));
        hubPanel.mat.uniforms.uBias.value = 0;

        for (const c of cards) {
          const born = clamp(spring(t, c.at - 0.05, 7.5, 0.72));
          const p = c.panel;
          const fl = new THREE.Vector3(drift(t, c.i + 1, 0.11, 0.55), drift(t, c.i + 7, 0.09, 0.5), drift(t, c.i + 13, 0.14, 0.45));
          p.group.position.copy(HUB).lerp(c.slot, born).add(fl.multiplyScalar(born));
          p.group.scale.setScalar(lerp(0.15, 1.0, clamp(born * 1.1)));
          // mostly face the camera (readable), keep a little 3D attitude
          q.copy(ctx.camera.quaternion);
          p.group.quaternion.identity().slerp(q, 0.72);
          p.group.rotateY(drift(t, c.i + 3, 0.12, 0.4));
          p.group.rotateX(drift(t, c.i + 5, 0.08, 0.4));
          const op = seg(t, c.at - 0.05, c.at + 0.22, ease.out) * (1 - seg(t, 6.85, 7.15));
          p.opacity = op;
          p.mat.uniforms.uBias.value = lerp(4.0, 0.0, seg(t, c.at, c.at + 0.4, ease.out));
          p.mat.uniforms.uSheen.value = lerp(-0.6, 1.8, seg(t, 5.6 + c.i * 0.08, 6.4 + c.i * 0.08, ease.inOut));
          p.mat.uniforms.uSheenAmt.value = 1.0;
          p.mat.uniforms.uRim.value = 0.18 + 0.5 * Math.exp(-Math.pow((t - c.at - 0.1) / 0.15, 2));
        }
        // connections react to the floating cards every frame
        cards.forEach((c, i) => {
          const l = spokes[i];
          const a = HUB.clone().add(c.slot.clone().sub(HUB).normalize().multiplyScalar(0.75));
          const b = anchor(c, HUB);
          l.update(a, b, camPos, new THREE.Vector3(0, 0.25 * Math.sign(c.slot.y - HUB.y || 1), 0.25));
          const u = l.mat.uniforms;
          u.uProgress.value = lerp(-0.05, 1.1, seg(t, 5.0 + i * 0.07, 5.55 + i * 0.07, ease.inOut));
          u.uIntensity.value = 0.95 * (1 - seg(t, 6.75, 7.05));
          u.uPulse.value = ((t - 5.3 - i * 0.21) * 0.9) % 1.3;
          u.uPulseAmt.value = seg(t, 5.3, 5.7);
        });
        PAIRS.forEach(([i, j], n) => {
          const l = links[n];
          const A = cards[i], B = cards[j];
          l.update(anchor(A, B.panel.group.position), anchor(B, A.panel.group.position), camPos, new THREE.Vector3(0, 0, 0.6));
          const u = l.mat.uniforms;
          u.uProgress.value = lerp(-0.05, 1.1, seg(t, 5.45 + n * 0.1, 6.0 + n * 0.1, ease.inOut));
          u.uIntensity.value = 0.55 * (1 - seg(t, 6.7, 7.0));
          u.uPulse.value = ((t - 5.7 - n * 0.3) * 0.7) % 1.3;
          u.uPulseAmt.value = 0.8;
        });
      }
      if (cap.group.visible) animateCaption(cap, t, 5.45, 6.3, 6.6);
    },
  };
}

// letters rise out of a soft defocus with a slight stagger; tracking relaxes
export function animateCaption(cap, t, tIn, tOut0, tOut1, stagger = 0.028) {
  const n = cap.count;
  for (const g of cap.glyphs) {
    const k = g.index - (n - 1) / 2;
    const a = seg(t, tIn + g.index * stagger, tIn + g.index * stagger + 0.5, ease.out);
    const out = seg(t, tOut0, tOut1, ease.inOut);
    g.mesh.position.set(g.base.x * lerp(1.12, 1.0, a) + k * 0.004 * out * 6, g.base.y + lerp(-0.05, 0, a) + out * 0.02, 0);
    g.mat.uniforms.uOpacity.value = a * (1 - out);
    g.mat.uniforms.uBias.value = lerp(3.5, 0, a) + out * 3.0;
    g.mat.uniforms.uGlow.value = 0.25 + 0.6 * (1 - a);
  }
}
