// 00:12–00:15 FINAL REVEAL
// Black. A thin violet ribbon crosses the frame and leaves a soft volumetric
// glow; the official VYNARC logo (untouched artwork) is revealed in its wake,
// a light glint runs over the metal, the camera eases back, and the tagline
// letters glide in along a curve. Then the light softly fades out.
import * as THREE from 'three';
import { Ribbon, Glow, FlatLogo, Text, BRAND } from './lib.js';
import { seg, ease, clamp, lerp, window4 } from '../animations/easing.js';

const R = new THREE.Vector3(0, 0, 80);   // a separate stage, far from the journey

function frameMetrics(ctx) {
  const D = 10.0;
  const visW = 2 * D * ctx.halfW;
  const logoW = Math.min(5.3, visW * (ctx.portrait ? 0.84 : 0.72));
  return { D, visW, logoW };
}

export function cameraKeys(ctx) {
  const { D } = frameMetrics(ctx);
  return [
    [12.0, 0.0, 0.18, R.z + D * 0.94, 0.0, 0.16, R.z, 0.0],
    [13.5, 0.0, 0.12, R.z + D * 1.0, 0.0, 0.12, R.z, 0.0],
    [15.0, 0.0, 0.08, R.z + D * 1.09, 0.0, 0.1, R.z, 0.0],
  ];
}

export function create(ctx) {
  const { S, scene, overlay, tex } = ctx;
  const { D, visW, logoW } = frameMetrics(ctx);
  const group = new THREE.Group();
  group.position.copy(R);
  scene.add(group);
  const logo = new FlatLogo(S, tex.vynarc_logo_trim, logoW / (tex.vynarc_logo_trim.userData.w / tex.vynarc_logo_trim.userData.h));
  const logoY = ctx.portrait ? 0.55 : 0.32;
  logo.mesh.position.set(0, logoY, 0);
  logo.mesh.renderOrder = 10;
  group.add(logo.mesh);
  const back = new Glow(S, BRAND.deep, logoW * 1.5, 2.4);
  back.mesh.position.set(0, logoY, -0.6);
  group.add(back.mesh);
  const hit = new Glow(S, BRAND.neon, logoW * 0.5, 4.0);
  // the symbol's arc head in the trimmed artwork: 27.7% of the width, 16% of the height above centre
  hit.mesh.position.set(-logoW * 0.5 + logoW * 0.277, logoY + (logoW / 4.74) * 0.164, 0.1);
  group.add(hit.mesh);

  const rib = new Ribbon(S, { segments: 220 });
  group.add(rib.mesh);
  const span = visW * 0.78;
  const ribPoint = (u, t) => new THREE.Vector3(
    lerp(-span, span, u),
    logoY - 0.05 + 0.55 * Math.sin(u * Math.PI * 1.1 - 0.5) * (ctx.portrait ? 1.6 : 1) - 0.25,
    0.55 + 0.6 * Math.sin(u * 2.4 + 0.6),
  );
  const trail = [];
  for (let i = 0; i < 9; i++) {
    const g = new Glow(S, i % 2 ? BRAND.deep : BRAND.violet, visW * 0.32, 2.6);
    g.u = 0.08 + (i / 8) * 0.84;
    g.mesh.position.copy(ribPoint(g.u, 12.5)).add(new THREE.Vector3(0, 0, -0.4));
    group.add(g.mesh);
    trail.push(g);
  }

  const lines = ctx.portrait ? ['CREATE.', 'CONNECT.', 'ORGANIZE.'] : ['CREATE. CONNECT. ORGANIZE.'];
  const tag = new Text(S, lines, { size: ctx.portrait ? 0.066 : 0.06, weight: 500, tracking: ctx.portrait ? 0.34 : 0.4, color: BRAND.text, lineGap: 1.55 });
  tag.group.scale.setScalar(Math.min(1, (ctx.aspect * 2 * 0.8) / tag.width));
  // place under the logo (convert world height at distance D to overlay units)
  const toO = 1 / (D * ctx.halfH);
  const logoH = logoW / 4.74;
  tag.group.position.set(0, (logoY - 0.1 - logoH / 2) * toO - (ctx.portrait ? 0.25 : 0.12) - tag.height * tag.group.scale.y / 2, 0);
  overlay.add(tag.group);

  const headU = (t) => lerp(-0.05, 1.15, seg(t, 12.05, 12.95, ease.cine));

  return {
    update(t) {
      const vis = t >= 11.98;
      group.visible = vis; tag.group.visible = vis && t > 13.1;
      if (!vis) return;
      back.face(ctx.camera); hit.face(ctx.camera);
      // ribbon sweep
      rib.update((u) => ribPoint(u, t), (u) => 0.16 + 0.12 * Math.sin(Math.PI * u), (u) => 0.9 * Math.sin(u * 3.2 + t * 1.2) + 0.4, new THREE.Vector3(0, 1, 0));
      const ru = rib.mat.uniforms;
      ru.uTime.value = t;
      ru.uHead.value = headU(t);
      ru.uTail.value = lerp(-0.35, 1.15, seg(t, 12.3, 13.4, ease.inOut));
      ru.uHeadGlow.value = 1.0;
      ru.uIntensity.value = 1.5;
      ru.uCoreOffset.value = 0.25; ru.uCoreWidth.value = 0.12; ru.uSoftness.value = 2.4;
      ru.uBodyAmt.value = 0.7; ru.uSilverAmt.value = 0.7;
      // soft volumetric glow left in its wake (persists, decays slowly)
      const hu = headU(t);
      for (const g of trail) {
        g.face(ctx.camera);
        const passT = 12.05 + 0.9 * (g.u + 0.05) / 1.2;
        const a = t < passT ? 0 : (1 - Math.exp(-(t - passT) / 0.08)) * Math.exp(-(t - passT) / 1.1);
        g.mat.uniforms.uIntensity.value = 0.085 * a * (1 - seg(t, 14.3, 15.0));
      }
      // logo revealed in the ribbon's wake
      const lu = logo.mat.uniforms;
      const headX = lerp(-span, span, hu);
      lu.uReveal.value = (headX + logoW / 2) / logoW - 0.05;
      lu.uRevealSoft.value = 0.09;
      lu.uOpacity.value = 1;
      lu.uGlow.value = 0.45 * Math.exp(-Math.max(0, t - 12.85) / 0.32) * seg(t, 12.75, 12.86);
      lu.uSweep.value = lerp(-0.25, 1.3, seg(t, 13.05, 13.8, ease.inOut));
      lu.uSweepAmt.value = 0.85;
      lu.uBias.value = 0;
      back.mat.uniforms.uIntensity.value = 0.06 * seg(t, 12.6, 13.2) * (1 - seg(t, 14.3, 15.0));
      hit.mat.uniforms.uIntensity.value = 0.7 * Math.exp(-Math.max(0, t - 12.85) / 0.28) * seg(t, 12.78, 12.86);
      // tagline: letters glide in along an arc, staggered, defocus -> sharp
      for (const gph of tag.glyphs) {
        const i = gph.index;
        const a = seg(t, 13.2 + i * 0.026, 13.2 + i * 0.026 + 0.6, ease.out);
        const s = 1 - a;
        gph.mesh.position.set(gph.base.x - 0.18 * s, gph.base.y - 0.32 * s * s - 0.04 * s, 0);
        gph.mesh.rotation.z = 0.5 * s;
        gph.mat.uniforms.uOpacity.value = Math.min(1, a * 1.6);
        gph.mat.uniforms.uBias.value = 3.0 * s;
        gph.mat.uniforms.uGlow.value = 0.1 + 0.5 * s;
      }
    },
  };
}
