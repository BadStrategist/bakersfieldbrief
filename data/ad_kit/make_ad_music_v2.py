#!/usr/bin/env python3
"""Original upbeat electronic soundtrack for the BakersfieldBrief ad v2.

128 BPM, sidechain-pumped, with a real structure:
  bar1 filtered intro + BOOM SFX   -> hook
  bar2 + hats/claps                -> heli
  bar3 + bass                      -> street
  bar4 riser                       -> skyline
  bar5 DROP (full)                 -> sunrise
  bars6-7 full                     -> value
  bars8-9 brand section + end hit  -> brand card
Exports hitmap.json (beat times, drops, sfx) so the video composer syncs.
"""
from __future__ import annotations

import json
import wave
import numpy as np

SR = 44100
BPM = 128.0
BEAT = 60.0 / BPM          # 0.46875 s
BAR = 4 * BEAT             # 1.875 s
N_BARS = 9
DUR = N_BARS * BAR         # 16.875 s? -> extend: 9 bars = 16.875, add outro to ~19.7
OUTRO = 2.8
DUR = N_BARS * BAR + OUTRO
N = int(SR * DUR)
t_all = np.arange(N) / SR
rng = np.random.default_rng(42)

BEATS = [b * BEAT for b in range(int(DUR / BEAT) + 1)]
KICKS = [b for b in BEATS if b < DUR - 0.1]
DROPS = [4 * BAR]          # t=7.5 (sunrise)
BRAND_HIT = [8 * BAR]      # t=15.0
SFX = [{"t": 0.0, "kind": "boom"}, {"t": 4 * BAR - 1.2, "kind": "riser"},
       {"t": 4 * BAR, "kind": "drop"}, {"t": 8 * BAR, "kind": "hit"},
       {"t": DUR - 0.9, "kind": "end"}]


def env_ar(n, a=0.004, r=0.1):
    e = np.ones(n)
    a_n = max(1, int(a * SR)); r_n = max(1, int(r * SR))
    e[:a_n] = np.linspace(0, 1, a_n)
    if r_n < n:
        e[-r_n:] *= np.exp(-np.linspace(0, 7, r_n))
    return e


def kick(pos, dur=0.16):
    out = np.zeros(N)
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(dur * SR), N - i)
        tt = np.arange(n) / SR
        f = 150 * np.exp(-tt * 30) + 44
        ph = 2 * np.pi * np.cumsum(f) / SR
        out[i:i + n] += np.sin(ph) * np.exp(-tt * 30) * 1.0
    return out


def clap(pos, dur=0.18):
    out = np.zeros(N)
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(dur * SR), N - i)
        noise = rng.standard_normal(n)
        bp = np.diff(noise, prepend=0) * 0.5 + np.diff(noise, prepend=0, append=0)[:n] * 0.3
        out[i:i + n] += bp * np.exp(-np.arange(n) / SR * 34) * 0.6
    return out


def hat(pos, dur=0.045, open_=False):
    out = np.zeros(N)
    d = 0.16 if open_ else dur
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(d * SR), N - i)
        noise = rng.standard_normal(n)
        hp = np.diff(noise, prepend=0) * 0.9
        out[i:i + n] += hp * np.exp(-np.arange(n) / SR * (16 if open_ else 80)) * (0.34 if open_ else 0.22)
    return out


def pluck_saw(f, n, cutoff=1800):
    tt = np.arange(n) / SR
    raw = 2.0 * (tt * f % 1.0) - 1.0
    raw += 0.4 * (2.0 * (tt * f * 2 % 1.0) - 1.0)
    lp = np.zeros(n); acc = 0.0
    a = min(1.0, cutoff / (SR / 2) * np.pi * 0.5)
    for k in range(n):
        acc += a * (raw[k] - acc)
        lp[k] = acc
    return lp


def bass_notes():
    out = np.zeros(N)
    seq = ["C", "G", "Am", "F"] * 2 + ["C", "G", "Am", "F"] + ["C"]
    roots = {"C": 65.41, "G": 98.00, "Am": 110.00, "F": 87.31}
    for bar_i, ch in enumerate(seq):
        t0 = bar_i * BAR
        root = roots[ch]
        for e in range(8):
            ts = t0 + e * BEAT / 2
            if ts >= DUR: break
            i = int(ts * SR)
            n = int(BEAT / 2 * 1.7)
            if i + n > N: n = N - i
            if n <= 0: continue
            f = root * (1.0 if e % 2 == 0 else 1.5)
            note = pluck_saw(f, n, cutoff=1200 if bar_i < 4 else 2400)
            out[i:i + n] += note * env_ar(n, 0.003, 0.12) * 0.5
    # sidechain pump on every kick
    duck = np.ones(N)
    for b in KICKS:
        i = int(b * SR); n = int(0.14 * SR)
        if i + n < N:
            duck[i:i + n] = 0.35
    return out * duck


def stabs():
    out = np.zeros(N)
    prog = [["C", "G", "Am", "F"]] * 9
    chords = {"C": [261.63, 329.63, 392.00], "G": [246.94, 311.13, 392.00],
              "Am": [220.00, 261.63, 329.63], "F": [174.61, 220.00, 261.63]}
    for bar_i, seq in enumerate(prog):
        for k, ch in enumerate(seq):
            t0 = bar_i * BAR + k * BEAT
            i = int(t0 * SR)
            n = int(BEAT * 0.4)
            if i + n > N: n = N - i
            if n <= 0: continue
            raw = np.zeros(n)
            for det in (-0.005, 0.0, 0.005):
                for f in chords[ch]:
                    raw += pluck_saw(f * (1 + det), n, cutoff=3500) * 0.12
            gain = 0.35 if bar_i >= 4 else 0.12   # only full after drop
            out[i:i + n] += raw * env_ar(n, 0.002, 0.14) * gain
    return out


def arp():
    out = np.zeros(N)
    pat = [523.25, 659.25, 783.99, 659.25]
    for bar_i in range(9):
        t0 = bar_i * BAR
        if bar_i < 4:
            continue
        for e in range(16):
            ts = t0 + e * BEAT / 4
            if ts >= DUR: break
            i = int(ts * SR)
            n = int(BEAT / 4 * 0.55)
            if i + n > N: n = N - i
            if n <= 0: continue
            tt = np.arange(n) / SR
            f = pat[e % 4]
            wave_ = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt)
            out[i:i + n] += wave_ * env_ar(n, 0.002, 0.09) * 0.13
    return out


def boom(t0):
    i = int(t0 * SR); n = int(1.4 * SR)
    if i + n > N: n = N - i
    tt = np.arange(n) / SR
    sub = np.sin(2 * np.pi * (70 * np.exp(-tt * 6) + 38) * tt) * np.exp(-tt * 5)
    noise = rng.standard_normal(n) * np.exp(-tt * 40) * 0.5
    out = np.zeros(N)
    out[i:i + n] = (sub * 0.9 + noise * 0.3)
    return out


def riser(t0, dur=1.2):
    i = int(t0 * SR); n = int(dur * SR)
    if i + n > N: n = N - i
    noise = rng.standard_normal(n)
    tt = np.arange(n) / SR
    sw = np.sin(2 * np.pi * (300 + 2200 * tt / dur) * tt) * 0.4
    e = np.linspace(0, 1, n) ** 2.5
    out = np.zeros(N)
    out[i:i + n] = (noise * 0.5 + sw) * e * 0.3
    return out


def hit(t0, dur=1.6):
    i = int(t0 * SR); n = int(dur * SR)
    if i + n > N: n = N - i
    tt = np.arange(n) / SR
    low = np.sin(2 * np.pi * (90 * np.exp(-tt * 5) + 52) * tt) * np.exp(-tt * 3)
    noise = rng.standard_normal(n) * np.exp(-tt * 12) * 0.2
    out = np.zeros(N)
    out[i:i + n] = (low * 0.9 + noise) * env_ar(n, 0.002, 0.6)
    return out


def static_burst(t0, dur=0.25):
    """Radio-static texture right at the top — scanner vibe."""
    i = int(t0 * SR); n = int(dur * SR)
    if i + n > N: n = N - i
    noise = rng.standard_normal(n)
    bp = np.diff(noise, prepend=0) * 0.7
    out = np.zeros(N)
    out[i:i + n] = bp * np.exp(-np.arange(n) / SR * 18) * 0.35
    return out


# ---- build mix ----
mix = np.zeros(N)
# intro filtered: kick only, low gain
mix += kick(KICKS) * np.where(t_all < BAR, 0.45, 1.0)

clap_times = [b + BEAT * 1 for b in BEATS if b + BEAT < DUR] + [b + BEAT * 3 for b in BEATS if b + BEAT * 3 < DUR]
clap_times = [c for c in clap_times if c >= BAR * 2]          # claps from bar 2
mix += clap(clap_times) * np.where(t_all < BAR * 2, 0.0, 1.0)

off8 = [o for o in np.arange(BEAT / 2, DUR, BEAT / 2)]
mix += hat([o for o in off8 if (o % BEAT) > 0.34 or ((o // BEAT) % 2 == 0)], 0.04) * np.where(t_all < BAR, 0.2, 1.0)
mix += hat([o for o in np.arange(BEAT * 3.5, DUR, BEAT * 4)], 0.16, open_=True)

mix += bass_notes() * np.where(t_all < BAR * 3, 0.0, 1.0)
mix += stabs()
mix += arp()

mix += static_burst(0.0)
mix += boom(0.0)
mix += riser(4 * BAR - 1.2)
mix += hit(4 * BAR, 1.6)      # sunrise drop hit
mix += hit(8 * BAR, 2.0)      # brand section hit
mix += riser(DUR - 1.4, 1.0)
mix += hit(DUR - 0.4, 1.2)    # end

# master
mix = np.tanh(mix * 1.15)
mix *= 0.9 / (np.max(np.abs(mix)) + 1e-9)
fn = int(0.05 * SR)
mix[:fn] *= np.linspace(0, 1, fn)
mix[-fn:] *= np.linspace(1, 0, fn)

stereo = np.stack([mix, mix], axis=1)
pcm = (stereo * 32767).astype(np.int16)
with wave.open(r"C:\Users\tscac\Projects\BakersfieldBrief.com\data\ad_kit\ad_music_v2.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())

# RMS envelope per video frame (24fps) for the waveform motif
FPS = 24
TOTAL = int(DUR * FPS)
env = []
for fi in range(TOTAL):
    i0 = int(fi / FPS * SR); i1 = int((fi + 1) / FPS * SR)
    seg = mix[i0:i1]
    env.append(float(np.sqrt(np.mean(seg ** 2)) if len(seg) else 0.0))
env = np.array(env)
env = env / (env.max() + 1e-9)

hitmap = {"beats": BEATS, "drops": DROPS, "brand_hit": BRAND_HIT,
          "sfx": SFX, "duration": DUR, "bpm": BPM,
          "env": [float(x) for x in env]}
with open(r"C:\Users\tscac\Projects\BakersfieldBrief.com\data\ad_kit\hitmap.json", "w") as f:
    json.dump(hitmap, f)
print(f"WAV: {DUR:.2f}s  env points: {len(env)}  beats: {len(BEATS)}")
