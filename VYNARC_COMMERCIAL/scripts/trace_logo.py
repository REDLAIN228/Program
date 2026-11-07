"""Derive 3D-ready geometry of the official VYNARC symbol from the official PNG.

The polygons and the orbit ellipse were measured on the alpha channel of
assets/vynarc_logo_official.png (see README, "Logo fidelity").  This script
re-validates them against the alpha mask (coverage / IoU) and writes
animations/logo_geometry.json in logo units: symbol height = 2.0, origin at
the symbol's bbox centre, +y up.  Nothing here alters the official artwork;
the PNG itself is used untouched for every flat logo appearance.
"""
import json, pathlib
import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
png = Image.open(ROOT / "assets/vynarc_logo_official.png").convert("RGBA")
alpha = np.array(png)[..., 3]

# Measured on the alpha mask (image px, y down).
LEFT = [(143, 190), (320, 186), (445, 410), (470, 455), (430, 566), (368, 566)]
RIGHT = [(579, 186), (725, 186), (473, 566), (375, 566), (360, 552)]
ELLIPSE = dict(cx=404.41, cy=453.12, a=293.55, b=112.56, ux=0.9062, uy=-0.4228)
ARC_PTS = [(160, 490), (265, 402.5), (400, 332.5), (500, 301), (600, 296), (665, 322.5)]
SYMBOL_BBOX = (143, 186, 725, 566)
WORDMARK_BBOX = (963, 300, 2048, 470)  # measured below, refined at runtime

# --- validation: polygons vs alpha inside symbol bbox (arc excluded roughly)
mask = Image.new("L", png.size, 0)
d = ImageDraw.Draw(mask)
d.polygon(LEFT, fill=255)
d.polygon(RIGHT, fill=255)
poly = np.array(mask) > 0
x0, y0, x1, y1 = SYMBOL_BBOX
a = alpha[y0:y1 + 1, x0:x1 + 1] > 128
p = poly[y0:y1 + 1, x0:x1 + 1]
iou = (a & p).sum() / max(1, (a | p).sum())

def theta_of(px, py):
    e = ELLIPSE
    dx, dy = px - e["cx"], py - e["cy"]
    u = np.array([e["ux"], e["uy"]]); w = np.array([-e["uy"], e["ux"]])
    return float(np.arctan2((dx * w[0] + dy * w[1]) / e["b"], (dx * u[0] + dy * u[1]) / e["a"]))

thetas = [theta_of(*q) for q in ARC_PTS]

# wordmark bbox (columns right of the symbol)
cols = np.where((alpha[:, 760:] > 128).any(0))[0] + 760
rows = np.where((alpha[:, 760:] > 128).any(1))[0]
WORDMARK_BBOX = (int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max()))

cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
s = 2.0 / (y1 - y0)
conv = lambda q: [round((q[0] - cx) * s, 5), round(-(q[1] - cy) * s, 5)]

out = {
    "source": "assets/vynarc_logo_official.png",
    "image_size": list(png.size),
    "symbol_bbox_px": list(SYMBOL_BBOX),
    "wordmark_bbox_px": list(WORDMARK_BBOX),
    "px_to_unit": s,
    "center_px": [cx, cy],
    "left_stroke": [conv(q) for q in LEFT],
    "right_stroke": [conv(q) for q in RIGHT],
    "corner_radius": round(14 * s, 5),
    "orbit": {
        "center": conv((ELLIPSE["cx"], ELLIPSE["cy"])),
        "a": round(ELLIPSE["a"] * s, 5),
        "b": round(ELLIPSE["b"] * s, 5),
        "u": [ELLIPSE["ux"], -ELLIPSE["uy"]],
        "theta_tail": round(thetas[0], 4),
        "theta_head": round(thetas[-1], 4),
        "samples_theta": [round(t, 4) for t in thetas],
        "max_thickness": round(24 * s, 5),
    },
    "validation": {"symbol_polygon_iou_vs_alpha": round(float(iou), 4)},
}
(ROOT / "animations/logo_geometry.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out["validation"]), "thetas", [round(t, 3) for t in thetas], "wordmark", WORDMARK_BBOX)
