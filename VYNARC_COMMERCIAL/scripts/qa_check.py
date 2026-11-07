"""Automated QA for the rendered commercial.

    python3 scripts/qa_check.py [video ...]      (default: every renders/*.mp4)

Checks: container/stream specs, duration, motion continuity (unexpected
frame-difference spikes), brand palette (hue of saturated bright pixels),
official-logo fidelity in the final frame (correlation against the untouched
PNG), black head/tail, audio peak/RMS and onset alignment with the timeline.
Writes previews/qa_report.json and previews/qa_*.png diagnostic images.
"""
import json, pathlib, subprocess, sys
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
TL = json.loads((ROOT / "animations/timeline.json").read_text())


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,bit_rate,sample_rate,channels,pix_fmt:format=duration,size,bit_rate",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)


def frames(p, w, h, fps=30):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={fps},scale={w}:{h}:flags=area", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def hue_stats(fr):
    x = fr.reshape(-1, 3).astype(float) / 255
    mx, mn = x.max(1), x.min(1)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    sel = (mx > 0.25) & (sat > 0.35)
    if sel.sum() == 0:
        return {}
    r, g, b = x[sel].T
    d = (mx - mn)[sel]
    h = np.where(mx[sel] == r, ((g - b) / d) % 6, np.where(mx[sel] == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    tot = len(h)
    return {
        "violet_250_310": round(float(((h >= 250) & (h <= 310)).sum() / tot), 4),
        "blue_200_250": round(float(((h >= 200) & (h < 250)).sum() / tot), 4),
        "magenta_310_340": round(float(((h > 310) & (h <= 340)).sum() / tot), 4),
        "orange_red_0_60_or_340_360": round(float(((h < 60) | (h > 340)).sum() / tot), 4),
        "samples": int(tot),
    }


def logo_fidelity(frame_rgb):
    """correlate the brightest compact region with the official artwork"""
    img = frame_rgb.astype(float).mean(2)
    H, W = img.shape
    m = img > 45
    rows = np.nonzero(m.sum(1) > 2)[0]
    if len(rows) < 5:
        return None
    # split bright rows into vertical clusters (logo / tagline) and keep the tallest
    groups, cur = [], [rows[0]]
    for r in rows[1:]:
        if r - cur[-1] > max(3, H // 90):
            groups.append(cur); cur = [r]
        else:
            cur.append(r)
    groups.append(cur)
    g = max(groups, key=len)
    y0, y1 = g[0], g[-1] + 1
    cols = np.nonzero(m[y0:y1].sum(0) > 0)[0]
    x0, x1 = cols[0], cols[-1] + 1
    ref = Image.open(ROOT / "assets/vynarc_logo_official.png").convert("RGBA")
    a = np.array(ref).astype(float)
    bb = Image.fromarray((a[..., 3] > 60).astype(np.uint8) * 255).getbbox()
    ref = ref.crop(bb)
    best = -1
    for pad in (0, 2, 4, 6):
        X0, X1, Y0, Y1 = int(x0) - pad, int(x1) + pad, int(y0) - pad, int(y1) + pad
        if X1 - X0 < 20 or Y1 - Y0 < 5:
            continue
        crop = img[max(0, Y0):Y1, max(0, X0):X1]
        r = np.array(ref.resize((crop.shape[1], crop.shape[0]), Image.LANCZOS)).astype(float)
        lum = (r[..., :3].mean(2) * r[..., 3] / 255)
        c = np.corrcoef(lum.ravel(), crop.ravel())[0, 1]
        best = max(best, c)
    return round(float(best), 4)


def audio_check(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    if len(a) == 0:
        return {"present": False}
    hop = 80
    env = np.array([np.sqrt((a[i:i + hop] ** 2).mean()) for i in range(0, len(a) - hop, hop)])
    on = np.maximum(0, np.diff(np.log(env + 1e-4)))
    hits = []
    for ev in TL["events"]:
        if ev["type"] in ("impact", "logo_hit", "ui_blip", "ui_pop", "metal"):
            i = int(ev["t"] * 100)
            w = on[max(0, i - 3): i + 6]
            hits.append({"t": ev["t"], "type": ev["type"], "onset_offset_ms": int((np.argmax(w) - min(3, i)) * 10)})
    return {"present": True, "peak_dbfs": round(float(20 * np.log10(np.abs(a).max() + 1e-9)), 2),
            "rms_dbfs": round(float(20 * np.log10(np.sqrt((a ** 2).mean()) + 1e-9)), 2), "onsets": hits}


def check(p):
    info = probe(p)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    W, H = int(v["width"]), int(v["height"])
    sw = 320; sh = int(round(sw * H / W / 2) * 2)
    fr = frames(p, sw, sh)
    g = fr.astype(float).mean(3)
    d = np.abs(np.diff(g, axis=0)).mean((1, 2))
    med = np.array([np.median(d[max(0, i - 4): i + 5]) for i in range(len(d))])
    spikes = [{"t": round((i + 1) / 30, 3), "diff": round(float(d[i]), 2)} for i in range(len(d)) if d[i] > 3 * med[i] + 6]
    full = frames(p, min(W, 1920), int(min(W, 1920) * H / W), fps=1)
    logo = logo_fidelity(full[min(14, len(full) - 1)]) if len(full) else None
    rep = {
        "file": str(p.relative_to(ROOT)), "size_mb": round(int(info["format"]["size"]) / 1e6, 1),
        "duration": float(info["format"]["duration"]), "video": v,
        "audio": [s for s in info["streams"] if s["codec_type"] == "audio"],
        "first_frame_mean": round(float(g[0].mean()), 2), "last_frame_mean": round(float(g[-1].mean()), 2),
        "motion_spikes": spikes, "palette": hue_stats(fr[::3]), "logo_correlation_t14": logo,
        "audio_check": audio_check(p),
    }
    # diagnostic plot: frame-difference curve
    Wp, Hp = 900, 160
    img = np.full((Hp, Wp, 3), 16, np.uint8)
    xs = (np.arange(len(d)) / max(1, len(d) - 1) * (Wp - 1)).astype(int)
    ys = (Hp - 1 - np.clip(d / max(1, d.max()) * (Hp - 10), 0, Hp - 1)).astype(int)
    for x, y in zip(xs, ys):
        img[y:, x] = (139, 61, 255)
    for sc in TL["scenes"]:
        img[:, int(sc["start"] / TL["duration"] * (Wp - 1))] = (200, 200, 200)
    Image.fromarray(img).save(ROOT / f"previews/qa_motion_{p.stem}.png")
    return rep


if __name__ == "__main__":
    vids = [pathlib.Path(x).resolve() for x in sys.argv[1:]] or sorted((ROOT / "renders").glob("*.mp4"))
    reps = [check(p) for p in vids]
    out = ROOT / "previews/qa_report.json"
    out.write_text(json.dumps(reps, indent=2, ensure_ascii=False))
    for r in reps:
        print(r["file"], f'{r["video"]["width"]}x{r["video"]["height"]}', r["video"]["codec_name"], r["video"]["r_frame_rate"],
              f'{r["duration"]:.3f}s', f'{r["size_mb"]}MB', "logo_corr", r["logo_correlation_t14"], "palette", r["palette"],
              "spikes", r["motion_spikes"], "audio", {k: v for k, v in r["audio_check"].items() if k != "onsets"})
        print("   onsets(ms):", [(o["t"], o["onset_offset_ms"]) for o in r["audio_check"].get("onsets", [])])
