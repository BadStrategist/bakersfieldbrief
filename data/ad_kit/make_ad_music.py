#!/usr/bin/env python3
"""Synthesize an original upbeat soundtrack for the BakersfieldBrief ad.

124 BPM electronic: four-on-the-floor kick, claps, hats, driving bass,
chord stabs, 16th arp, riser into the sunrise beat, final brand hit.
Pure numpy -> WAV. No TTS, no sampled beds, no reused audio.
"""
from __future__ import annotations

import numpy as np
import wave

SR = 44100
BPM = 124
BEAT = 60.0 / BPM          # 0.4839 s
BAR = 4 * BEAT
DUR = 20.0
N = int(SR * DUR)
t_all = np.arange(N) / SR


def env_ar(n, a=0.005, r=0.08):
    """Tiny attack + exp decay envelope."""
    e = np.ones(n)
    a_n = max(1, int(a * SR)); r_n = max(1, int(r * SR))
    e[:a_n] = np.linspace(0, 1, a_n)
    if r_n < n:
        e[-r_n:] *= np.exp(-np.linspace(0, 6, r_n))
    return e


def kick(pos, dur=0.18):
    out = np.zeros(N)
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(dur * SR), N - i)
        tt = np.arange(n) / SR
        f = 120 * np.exp(-tt * 22) + 42
        ph = 2 * np.pi * np.cumsum(f) / SR
        out[i:i + n] += np.sin(ph) * np.exp(-tt * 26) * 1.0
    return out


def clap(pos, dur=0.16):
    out = np.zeros(N)
    rng = np.random.default_rng(7)
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(dur * SR), N - i)
        noise = rng.standard_normal(n)
        # crude bandpass ~ 1500 Hz via diff
        bp = np.diff(noise, prepend=0) * 0.5
        out[i:i + n] += bp * np.exp(-np.arange(n) / SR * 40) * 0.55
    return out


def hat(pos, dur=0.05, open_=False):
    out = np.zeros(N)
    rng = np.random.default_rng(11)
    d = 0.18 if open_ else dur
    for p in pos:
        i = int(p * SR)
        if i >= N: break
        n = min(int(d * SR), N - i)
        noise = rng.standard_normal(n)
        hp = np.diff(noise, prepend=0) * 0.8
        out[i:i + n] += hp * np.exp(-np.arange(n) / SR * (14 if open_ else 70)) * 0.30
    return out


def saw(f, n):
    tt = np.arange(n) / SR
    return 2.0 * (tt * f % 1.0) - 1.0


def bassline(prog, pos_note_fn):
    """8th-note saw bass, one-pole lowpass, sidechain-ducked on kicks."""
    out = np.zeros(N)
    for (t0, freq) in pos_note_fn:
        i = int(t0 * SR)
        if i >= N: break
        n = min(int(BEAT / 2 * 1.9) , N - i)
        if n <= 0: continue
        raw = saw(freq, n) * 0.5 + saw(freq * 2, n) * 0.12
        # simple one-pole lowpass
        lp = np.zeros(n); acc = 0.0; a = 0.12
        for k in range(n):
            acc += a * (raw[k] - acc)
            lp[k] = acc
        out[i:i + n] += lp * env_ar(n, 0.004, 0.10)
    # sidechain: duck ~40% for 0.12s after each kick
    duck = np.ones(N)
    for b in np.arange(0, DUR, BEAT):
        i = int(b * SR); n = int(0.12 * SR)
        if i + n < N:
            duck[i:i + n] = 0.55
    return out * duck


def stabs(prog):
    """Four-on-the-floor chord stabs, detuned saw stack."""
    out = np.zeros(N)
    rng = np.random.default_rng(3)
    for (t0, chord) in prog:
        i = int(t0 * SR)
        if i >= N: break
        n = int(BEAT * 0.45)
        if i + n > N: n = N - i
        if n <= 0: continue
        raw = np.zeros(n)
        for det in (-0.006, 0.0, 0.006):
            for f in chord:
                tt = np.arange(n) / SR
                raw += saw(f * (1 + det), n) * 0.10
        raw *= env_ar(n, 0.003, 0.12)
        out[i:i + n] += raw
    return out


def arp(prog, pat):
    """16th-note plucky arpeggio over the progression."""
    out = np.zeros(N)
    for (t0, chord) in prog:
        for k, f in enumerate(pat):
            ts = t0 + k * BEAT / 4
            i = int(ts * SR)
            if i >= N: break
            n = int(BEAT / 4 * 0.7)
            if i + n > N: n = N - i
            if n <= 0: continue
            tt = np.arange(n) / SR
            wave_ = np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2 * tt)
            out[i:i + n] += wave_ * env_ar(n, 0.002, 0.10) * 0.16
    return out


def riser(t0, dur=1.8):
    i = int(t0 * SR); n = int(dur * SR)
    if i + n > N: n = N - i
    rng = np.random.default_rng(5)
    noise = rng.standard_normal(n)
    tt = np.arange(n) / SR
    sw = np.sin(2 * np.pi * (400 + 1600 * tt / dur) * tt) * 0.5
    e = np.linspace(0, 1, n) ** 2
    out = np.zeros(N)
    out[i:i + n] = (noise * 0.4 + sw) * e * 0.35
    return out


def hit(pos, dur=1.2):
    """Big final hit for the brand card."""
    i = int(pos * SR); n = int(dur * SR)
    if i + n > N: n = N - i
    tt = np.arange(n) / SR
    low = np.sin(2 * np.pi * (80 * np.exp(-tt * 4) + 55) * tt) * 0.9
    rng = np.random.default_rng(9)
    noise = rng.standard_normal(n) * np.exp(-tt * 9) * 0.25
    out = np.zeros(N)
    out[i:i + n] = (low + noise) * env_ar(n, 0.002, 0.5)
    return out


# ---- chord map (A minor-ish, uplifting pop) ----
F = {  # A4=440
    "C": [261.63, 329.63, 392.00],
    "G": [246.94, 311.13, 392.00],
    "Am": [220.00, 261.63, 329.63],
    "F": [174.61, 220.00, 261.63],
}
prog = []  # (beat_index, chord)
for bar in range(5):
    for k, ch in enumerate(["C", "G", "Am", "F"]):
        prog.append((bar * 4 + k, F[ch]))

mix = np.zeros(N)
beats = np.arange(0, DUR - 0.05, BEAT)
mix += kick([b for b in beats])
mix += clap([b + BEAT * 1 for b in beats if b + BEAT * 1 < DUR] + [b + BEAT * 3 for b in beats if b + BEAT * 3 < DUR])
off8 = np.arange(BEAT / 2, DUR - 0.05, BEAT / 2)
mix += hat([o for o in off8 if o % BEAT > 0.30 or (o // BEAT) % 2 == 0], 0.04)
mix += hat([o for o in np.arange(BEAT * 3.5, DUR - 0.05, BEAT * 4)], 0.18, open_=True)

bass_notes = []
for (bar, ch) in [(bar, ch) for bar in range(5) for ch in ["C", "G", "Am", "F"]]:
    root = {"C": 65.41, "G": 98.00, "Am": 110.00, "F": 87.31}[ch]
    for e in range(8):
        bass_notes.append((bar * 4 * BEAT + e * BEAT / 2, root * (1 if e % 2 == 0 else 1.5)))
mix += bassline(prog, bass_notes)

mix += stabs([(t, ch) for (t, ch) in prog])
arp_pat = [261.63, 392.00, 523.25, 392.00]
mix += arp(prog, arp_pat)

mix += riser(4 * BAR - 0.4)          # build into sunrise (bar 4 = shot 4)
mix += riser(4 * BAR + 2.0, 1.2)     # second pulse
mix += hit(4 * BAR + 0.0, 1.6)       # sunrise downbeat
mix += hit(DUR - 1.6, 2.0)           # brand card hit

# gentle master: soft clip + normalize
mix = np.tanh(mix * 1.1)
mix *= 0.92 / (np.max(np.abs(mix)) + 1e-9)
mix = mix * 0.9 + 0.1 * np.sin(2 * np.pi * 0.0 * t_all)  # dc guard
fade = np.ones(N); fn = int(0.4 * SR)
fade[:fn] = np.linspace(0, 1, fn); fade[-fn:] = np.linspace(1, 0, fn)
mix *= fade

stereo = np.stack([mix, mix], axis=1)
pcm = (stereo * 32767).astype(np.int16)
with wave.open(r"C:\Users\tscac\Projects\BakersfieldBrief.com\data\ad_kit\ad_music.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"WAV written: {DUR}s, {pcm.shape[0]} frames")
