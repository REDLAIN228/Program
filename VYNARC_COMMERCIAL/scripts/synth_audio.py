"""Original cinematic sound design for the VYNARC commercial, synthesised from
scratch with numpy (no samples, no third-party music).

Every hit is placed from animations/timeline.json — the same file the
animation reads — so picture and sound stay frame-locked.

    python3 scripts/synth_audio.py            -> audio/vynarc_sound.wav (48 kHz, 24-bit stereo)
                                              -> audio/stems/*.wav
"""
import json, pathlib, wave
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
TL = json.loads((ROOT / "animations/timeline.json").read_text())
SR = 48000
DUR = TL["duration"]
N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(20261107)


def stereo(x, pan=0.0):
    """equal-power pan, pan in [-1, 1] (scalar or array)"""
    a = (np.asarray(pan) + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)])


def env_adsr(n, a, d, s, r, sr=SR):
    a, d, r = int(a * sr), int(d * sr), int(r * sr)
    e = np.full(n, s, float)
    e[:a] = np.linspace(0, 1, a, endpoint=False) if a else e[:a]
    e[a:a + d] = np.linspace(1, s, d, endpoint=False)[: max(0, min(d, n - a))]
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 2
    return e


def place(bus, sig, at):
    i = int(at * SR)
    if i >= bus.shape[1]:
        return
    j = min(bus.shape[1], i + sig.shape[1])
    bus[:, i:j] += sig[:, : j - i]


def stft_filter(x, gain_fn, n_fft=2048, hop=512):
    """time-varying spectral shaping: gain_fn(freqs, times) -> gains"""
    win = np.hanning(n_fft)
    pad = np.concatenate([np.zeros(n_fft), x, np.zeros(n_fft)])
    frames = (len(pad) - n_fft) // hop + 1
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    S = np.fft.rfft(pad[idx] * win, axis=1)
    freqs = np.fft.rfftfreq(n_fft, 1 / SR)
    times = (np.arange(frames) * hop - n_fft + n_fft / 2) / SR
    S *= gain_fn(freqs[None, :], times[:, None])
    y = np.fft.irfft(S, axis=1) * win
    out = np.zeros(len(pad))
    norm = np.zeros(len(pad))
    for k in range(frames):
        out[k * hop:k * hop + n_fft] += y[k]
        norm[k * hop:k * hop + n_fft] += win ** 2
    out /= np.maximum(norm, 1e-3)
    return out[n_fft:n_fft + len(x)]


def bandpass_gain(fc, bw_oct):
    def g(f, tt):
        c = fc(tt)
        return np.exp(-0.5 * (np.log2(np.maximum(f, 1) / c) / bw_oct) ** 2)
    return g


def lowpass(x, fc):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (f / fc) ** 4), len(x))


def highpass(x, fc):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X * (1 / np.sqrt(1 + (fc / np.maximum(f, 1e-3)) ** 4)), len(x))


def smooth01(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


# ----------------------------------------------------------------- elements
def sub_drone():
    f = 41.2  # E1
    sw = smooth01((t - 0.1) / 1.6)
    dip = 1 - 0.75 * smooth01((t - 11.7) / 0.4) * (1 - smooth01((t - 12.75) / 0.15))
    e = sw * dip * (1 - smooth01((t - 14.25) / 0.75))
    lfo = 1 + 0.08 * np.sin(2 * np.pi * 0.23 * t)
    x = np.sin(2 * np.pi * f * t + 0.3 * np.sin(2 * np.pi * 0.11 * t)) + 0.28 * np.sin(2 * np.pi * 2 * f * t + 1.1)
    x += 0.12 * np.tanh(3 * np.sin(2 * np.pi * f * t))  # a little grit for small speakers
    return stereo(x * e * lfo * 0.42)


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


CHORDS = [  # (start, notes)  E minor world resolving to E major at the logo
    (0.0, [40, 47, 55, 66, 71]),     # Em(add9)
    (4.0, [36, 43, 55, 59, 64]),     # Cmaj7
    (7.0, [35, 43, 50, 57, 62]),     # G/B add9
    (10.0, [38, 45, 54, 57, 64]),    # D6/9 lift
    (12.8, [40, 47, 56, 63, 71]),    # E major add9 (logo)
]


def pad():
    out = np.zeros((2, N))
    for ci, (start, notes) in enumerate(CHORDS):
        end = CHORDS[ci + 1][0] if ci + 1 < len(CHORDS) else DUR
        e = smooth01((t - start + 0.35) / 0.7) * (1 - smooth01((t - end - 0.0) / 0.7)) if ci else (1 - smooth01((t - end) / 0.7))
        if ci == 0:
            e = e * smooth01((t - 0.3) / 2.0)
        if ci == len(CHORDS) - 1:
            e = smooth01((t - start + 0.05) / 0.5) * (1 - smooth01((t - 14.2) / 0.8))
        idx = np.nonzero(e > 1e-4)[0]
        if len(idx) == 0:
            continue
        tt = t[idx]
        # filter opens over the film, closes for the black at 12.0
        fc = 300 + 1700 * smooth01(tt / 10.0) - 1300 * smooth01((tt - 11.6) / 0.4) * (1 - smooth01((tt - 12.8) / 0.3)) + 900 * smooth01((tt - 12.8) / 0.6)
        for ni, n in enumerate(notes):
            f0 = midi(n)
            for v, det in enumerate((-0.07, 0.0, 0.07)):
                fv = f0 * 2 ** (det / 12)
                ph = rng.uniform(0, 2 * np.pi, 64)
                sig = np.zeros(len(idx))
                h = 1
                while h * fv < 6000 and h < 48:
                    amp = (1 / h) / np.sqrt(1 + (h * fv / fc) ** 4)
                    sig += amp * np.sin(2 * np.pi * h * fv * tt + ph[h])
                    h += 1
                pan = (ni / (len(notes) - 1) - 0.5) * 0.8 + (v - 1) * 0.25
                out[:, idx] += stereo(sig * e[idx] * 0.05, pan)
    return out


def noise_whoosh(at, dur, pan0, pan1, f0=250, f1=3000, gain=0.5, bw=0.9):
    n = int(dur * SR) + SR
    x = rng.standard_normal(n)
    tt = np.arange(n) / SR
    fc = lambda T: f0 * (f1 / f0) ** smooth01(T / dur)
    y = stft_filter(x, bandpass_gain(fc, bw))
    e = smooth01(tt / (dur * 0.7)) * (1 - smooth01((tt - dur * 0.7) / (dur * 0.5)))
    pan = pan0 + (pan1 - pan0) * smooth01(tt / dur)
    return stereo(y * e * gain, pan), -dur * 0.7


def impact(gain=0.6, f_hi=95, f_lo=34, decay=1.4):
    n = int(2.5 * SR)
    tt = np.arange(n) / SR
    f = f_lo + (f_hi - f_lo) * np.exp(-tt * 9)
    ph = 2 * np.pi * np.cumsum(f) / SR
    boom = np.sin(ph) * np.exp(-tt / decay) * smooth01(tt / 0.004)
    crack = lowpass(rng.standard_normal(n), 1800) * np.exp(-tt / 0.06) * 0.6
    x = np.tanh(1.6 * (boom + crack)) * gain
    return stereo(x)


def metal(gain=0.6, f0=392.0, decay=1.8):
    n = int(3.5 * SR)
    tt = np.arange(n) / SR
    ratios = [1.0, 2.76, 5.40, 8.93, 13.34, 1.5]
    amps = [1.0, 0.55, 0.32, 0.18, 0.08, 0.25]
    out = np.zeros((2, n))
    for k, (r, a) in enumerate(zip(ratios, amps)):
        for side, det in enumerate((-1.5, 1.5)):
            fr = f0 * r + det * (k + 1) * 0.3
            s = a * np.sin(2 * np.pi * fr * tt + rng.uniform(0, 6.28)) * np.exp(-tt / (decay / (1 + 0.35 * k)))
            out[side] += s
    att = smooth01(tt / 0.02)
    return out * att * gain * 0.18


def blip(semi=0, gain=0.25, pan=0.0):
    n = int(0.5 * SR)
    tt = np.arange(n) / SR
    f = midi(76 + semi)
    x = np.sin(2 * np.pi * f * tt + 0.8 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 30)) * np.exp(-tt * 18)
    x += 0.3 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 30)
    click = rng.standard_normal(n) * np.exp(-tt * 900) * 0.15
    return stereo((x + click) * gain * smooth01(tt / 0.002), pan)


def pop(semi=0, gain=0.22, pan=0.0):
    n = int(0.6 * SR)
    tt = np.arange(n) / SR
    f = midi(64 + semi) * (1 + 0.25 * np.exp(-tt * 40))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9)
    air = stft_filter(rng.standard_normal(n), bandpass_gain(lambda T: 4000 + 0 * T, 0.6)) * np.exp(-tt * 14) * 0.25
    return stereo((x + air) * gain, pan)


def pulses(dur, gain=0.12, rate=0.125):
    n = int((dur + 0.5) * SR)
    out = np.zeros((2, n))
    k = 0
    while k * rate < dur:
        p = blip(semi=[0, 7, 12, 7][k % 4] - 12, gain=gain * (0.6 + 0.4 * (k % 2 == 0)), pan=0.35 * np.sin(k * 1.3))
        i = int(k * rate * SR)
        j = min(n, i + p.shape[1])
        out[:, i:j] += p[:, : j - i] * (1 - k * rate / dur) ** 0.5
        k += 1
    return out


def shimmer(dur=0.9, gain=0.12, f=7000):
    n = int((dur + 0.6) * SR)
    tt = np.arange(n) / SR
    y = stft_filter(rng.standard_normal(n), bandpass_gain(lambda T: f * (0.8 + 0.4 * smooth01(T / dur)), 0.5))
    e = smooth01(tt / (dur * 0.5)) * (1 - smooth01((tt - dur * 0.5) / (dur * 0.6)))
    return np.stack([y * e, np.roll(y, 211) * e]) * gain


def sparkles(dur, gain=0.1, count=90):
    n = int((dur + 0.6) * SR)
    out = np.zeros((2, n))
    for k in range(count):
        at = (k / count) ** 0.8 * dur + rng.uniform(-0.02, 0.02)
        f = rng.uniform(2200, 6500)
        m = int(0.25 * SR)
        tt = np.arange(m) / SR
        g = np.sin(2 * np.pi * f * tt) * np.exp(-tt * rng.uniform(25, 60)) * smooth01(tt / 0.003)
        i = max(0, int(at * SR))
        j = min(n, i + m)
        out[:, i:j] += stereo(g[: j - i] * gain * (1 - k / count) ** 0.7 * rng.uniform(0.4, 1), rng.uniform(-0.8, 0.8))
    return out


def riser(dur, gain=0.3):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    y = stft_filter(rng.standard_normal(n), bandpass_gain(lambda T: 300 * (12 ** smooth01(T / dur)), 0.7))
    f = 110 * 2 ** (2.5 * (tt / dur) ** 2)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 + np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * 0.2
    e = (tt / dur) ** 2.2
    return np.stack([(y + tone) * e, (np.roll(y, 97) + tone) * e]) * gain


def logo_hit(gain=1.0):
    n = int(3.2 * SR)
    out = np.zeros((2, n))
    b = impact(gain=0.75 * gain, f_hi=80, f_lo=31, decay=1.6)
    out[:, : b.shape[1]] += b[:, :n]
    m = metal(gain=0.9 * gain, f0=329.6, decay=2.4)  # E4 metal ring
    out[:, : m.shape[1]] += m[:, :n]
    s = shimmer(1.6, 0.08 * gain, 8500)
    out[:, : s.shape[1]] += s[:, :n]
    return out


def air_swell(dur=0.6, gain=0.08):
    return shimmer(dur, gain, 3500)


# ---------------------------------------------------------------- reverb
def reverb(x, seconds=2.6, mix=0.3, predelay=0.02):
    n = int(seconds * SR)
    tt = np.arange(n) / SR
    out = np.zeros_like(x)
    L = x.shape[1] + n
    size = 1 << int(np.ceil(np.log2(L)))
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-tt * 6.9 / seconds)
        ir = lowpass(ir, 5200) * (1 - 0.0 * tt)
        ir[: int(predelay * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        y = np.fft.irfft(np.fft.rfft(x[ch], size) * np.fft.rfft(ir, size), size)[: x.shape[1]]
        out[ch] = y
    return x + out * mix


# ---------------------------------------------------------------- mix
def build():
    stems = {k: np.zeros((2, N)) for k in ("drone", "pad", "fx", "ui")}
    stems["drone"] += sub_drone()
    stems["pad"] += pad()
    fx, ui = stems["fx"], stems["ui"]
    for ev in TL["events"]:
        at, ty = ev["t"], ev["type"]
        if ty == "sub_swell":
            place(fx, shimmer(1.8, 0.03, 900), at)
        elif ty == "shimmer":
            place(fx, shimmer(1.0, 0.07, 6000), at)
        elif ty in ("whoosh", "whoosh_big"):
            big = ty == "whoosh_big"
            pan = ev.get("pan", [0, 0])
            sig, off = noise_whoosh(at, ev.get("dur", 0.7), pan[0], pan[1], f0=180 if big else 300,
                                    f1=4200 if big else 2600, gain=0.75 if big else 0.42, bw=1.1 if big else 0.8)
            place(fx, sig, at)  # event time = start, peak at +70% of dur
        elif ty == "impact":
            place(fx, impact(gain=ev.get("gain", 0.6)), at)
        elif ty == "metal":
            place(fx, metal(gain=ev.get("gain", 0.7)), at)
        elif ty == "sheen":
            place(fx, shimmer(0.7, 0.09, 9000), at)
        elif ty == "ui_blip":
            p = ev.get("pitch", 0)
            place(ui, blip(p, 0.2, pan=(p - 4) / 8), at)
        elif ty == "pulse_seq":
            place(ui, pulses(ev.get("dur", 1.0)), at)
        elif ty == "text_in":
            place(fx, air_swell(0.6, 0.06), at - 0.1)
        elif ty == "ui_cascade":
            place(ui, pulses(ev.get("dur", 0.7), gain=0.1, rate=0.06), at)
        elif ty == "ui_pop":
            p = ev.get("pitch", 0)
            place(ui, pop(p, 0.2, pan=(p - 3) / 7), at)
        elif ty == "dissolve":
            place(fx, sparkles(ev.get("dur", 0.9)), at)
        elif ty == "riser":
            place(fx, riser(ev.get("dur", 1.3)), at)
        elif ty == "logo_hit":
            place(fx, logo_hit(ev.get("gain", 1.0)), at)
    stems["fx"] = reverb(stems["fx"], 2.8, 0.38)
    stems["ui"] = reverb(stems["ui"], 1.6, 0.3)
    stems["pad"] = reverb(stems["pad"], 3.2, 0.45)
    mix = stems["drone"] * 1.0 + stems["pad"] * 1.0 + stems["fx"] * 1.0 + stems["ui"] * 0.9
    for ch in range(2):
        mix[ch] = highpass(mix[ch], 24)
    # master: gentle glue + soft clip, loudness ~ -14 LUFS-ish (RMS proxy), peak < -1 dBFS
    mix *= 10 ** (-16 / 20) / max(1e-6, np.sqrt((mix ** 2).mean()))
    mix = np.tanh(mix * 1.15) / 1.15
    mix *= 10 ** (-1.0 / 20) / max(1e-6, np.abs(mix).max())
    fade_in = smooth01(t / 0.05)
    fade_out = 1 - smooth01((t - (DUR - 0.25)) / 0.25)
    mix *= fade_in * fade_out
    return mix, stems


def write_wav(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.clip(x.T, -1, 1)
    y = (y * (2 ** 23 - 1) + rng.uniform(-0.5, 0.5, y.shape) + rng.uniform(-0.5, 0.5, y.shape)).astype(np.int32)
    b = np.zeros((y.shape[0], 2, 3), np.uint8)
    for c in range(2):
        v = y[:, c].astype(np.uint32)
        b[:, c, 0] = v & 255; b[:, c, 1] = (v >> 8) & 255; b[:, c, 2] = (v >> 16) & 255
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(3); w.setframerate(SR)
        w.writeframes(b.tobytes())


if __name__ == "__main__":
    mix, stems = build()
    write_wav(ROOT / "audio/vynarc_sound.wav", mix)
    for k, v in stems.items():
        write_wav(ROOT / f"audio/stems/{k}.wav", v / max(1e-6, np.abs(v).max()) * 0.89)
    print("peak dBFS", round(20 * np.log10(np.abs(mix).max()), 2), "rms dBFS", round(20 * np.log10(np.sqrt((mix ** 2).mean())), 2))
