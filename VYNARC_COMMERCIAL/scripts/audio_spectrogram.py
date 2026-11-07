"""Spectrogram of the soundtrack with the timeline events and scene borders
overlaid -> previews/qa_audio_spectrogram.png (visual sync check)."""
import json, pathlib, wave
import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
TL = json.loads((ROOT / "animations/timeline.json").read_text())
with wave.open(str(ROOT / "audio/vynarc_sound.wav")) as w:
    sr, n = w.getframerate(), w.getnframes()
    b = np.frombuffer(w.readframes(n), np.uint8).reshape(-1, 2, 3).astype(np.int32)
x = ((b[..., 0] | (b[..., 1] << 8) | (b[..., 2] << 16)) << 8 >> 8).mean(1) / 2 ** 23
nfft, hop = 2048, 256
win = np.hanning(nfft)
frames = (len(x) - nfft) // hop
S = np.abs(np.fft.rfft(np.stack([x[i * hop:i * hop + nfft] * win for i in range(frames)]), axis=1)).T
f = np.fft.rfftfreq(nfft, 1 / sr)
W, H = 1500, 420
logf = np.geomspace(25, 16000, H)
rows = np.searchsorted(f, logf)
img = 20 * np.log10(S[rows] + 1e-6)
img = np.clip((img - img.max() + 80) / 80, 0, 1)[::-1]
cols = np.linspace(0, frames - 1, W).astype(int)
img = img[:, cols]
rgb = np.stack([img ** 1.4 * 180, img ** 2.2 * 60, img ** 0.9 * 255], -1).astype(np.uint8)
im = Image.fromarray(rgb)
d = ImageDraw.Draw(im)
for sc in TL["scenes"]:
    xx = sc["start"] / TL["duration"] * W
    d.line([(xx, 0), (xx, H)], fill=(255, 255, 255), width=1)
    d.text((xx + 3, 3), sc["id"], fill=(255, 255, 255))
for ev in TL["events"]:
    xx = ev["t"] / TL["duration"] * W
    d.line([(xx, H - 40), (xx, H)], fill=(255, 210, 90), width=1)
im.save(ROOT / "previews/qa_audio_spectrogram.png")
print("saved previews/qa_audio_spectrogram.png")
