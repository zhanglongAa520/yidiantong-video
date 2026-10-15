"""程序化合成背景音乐与音效（全部由本脚本生成，无第三方素材，作者以 CC0 放弃版权）。
用法：python3 tools/make_audio.py   → 输出到 assets/audio/
依赖：numpy、ffmpeg
"""
import os, subprocess, wave
import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "audio")

def midi(n): return 440.0 * 2 ** ((n - 69) / 12)

def pluck(freq, dur, rng, decay=0.996, bright=0.5):
    """Karplus-Strong 拨弦（近似古筝/吉他）。"""
    n = int(SR * dur); p = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, p) * bright + rng.uniform(-1, 1, p) * (1 - bright) * 0.3
    out = np.zeros(n)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = decay * 0.5 * (buf[i % p] + buf[(i + 1) % p])
    return out * np.linspace(1, 0.0, n) ** 0.5

def tone(freq, dur, kind="sine"):
    t = np.arange(int(SR * dur)) / SR
    if kind == "tri": w = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * freq * t))
    else: w = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 3.5)
    return w * env

def add(track, sig, at, gain=1.0):
    i = int(at * SR); j = min(len(track), i + len(sig))
    if i < len(track): track[i:j] += sig[: j - i] * gain

def reverb(x, mix=0.3):
    y = x.copy()
    for d, g in [(0.031, .5), (0.047, .45), (0.071, .4), (0.113, .35), (0.167, .3)]:
        k = int(d * SR); z = np.zeros_like(x); z[k:] = x[:-k]
        for _ in range(3):
            z2 = np.zeros_like(z); z2[k:] = z[:-k] * g; z = z + z2
        y += z * g * mix
    return y

def guofeng(seed, length=64, root=62):
    rng = np.random.default_rng(seed); tr = np.zeros(SR * length)
    scale = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]   # 五声音阶（宫商角徵羽）
    beat = 60 / 66; t = 0.0; idx = 4
    while t < length - 3:
        idx = int(np.clip(idx + rng.choice([-2, -1, -1, 0, 1, 1, 2]), 0, len(scale) - 1))
        f = midi(root + scale[idx]); d = beat * rng.choice([1, 1, 2, 0.5])
        add(tr, pluck(f, 2.5, rng, 0.997, 0.7), t, 0.35)
        if rng.random() < 0.25: add(tr, pluck(f * 2, 1.2, rng, 0.995), t + beat * 0.25, 0.12)  # 装饰音
        t += d
    tt = np.arange(len(tr)) / SR   # 低音持续音（类箫/笙）
    drone = (np.sin(2 * np.pi * midi(root - 24) * tt) * 0.6 + np.sin(2 * np.pi * midi(root - 17) * tt) * 0.3)
    drone *= 0.08 * (0.7 + 0.3 * np.sin(2 * np.pi * tt / 8))
    return reverb(tr, 0.5) + drone

def light(seed, length=64, root=60):
    rng = np.random.default_rng(seed); tr = np.zeros(SR * length)
    beat = 60 / 108; prog = [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]]  # I-V-vi-IV
    t = 0.0; bar = 0
    while t < length - 2:
        ch = prog[bar % 4]
        for k in range(8):   # 八分音符分解和弦
            n = root + ch[[0, 1, 2, 1, 0, 2, 1, 2][k]] + (12 if k in (2, 5) else 0)
            add(tr, tone(midi(n), 0.6, "tri"), t + k * beat / 2, 0.16)
        add(tr, tone(midi(root - 12 + ch[0]), 1.6), t, 0.22)          # 低音
        for k in range(4):                                             # 软底鼓 + 沙锤
            kt = np.arange(int(SR * .15)) / SR
            add(tr, np.sin(2 * np.pi * (60 + 80 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 25), t + k * beat, 0.25)
            sh = rng.uniform(-1, 1, int(SR * .05)) * np.exp(-np.arange(int(SR * .05)) / SR * 80)
            add(tr, np.diff(sh, prepend=0), t + k * beat + beat / 2, 0.08)
        if rng.random() < 0.6:                                         # 旋律点缀
            add(tr, pluck(midi(root + 12 + rng.choice(ch)), 1.0, rng, 0.994, 0.8), t + beat * rng.integers(0, 4), 0.12)
        t += beat * 4; bar += 1
    return reverb(tr, 0.2)

def whoosh():
    n = int(SR * 0.7); rng = np.random.default_rng(7); x = rng.normal(0, 1, n)
    y = np.zeros(n); a = 0.0
    for i in range(n):  # 扫频低通
        c = 0.02 + 0.25 * np.sin(np.pi * i / n); a += c * (x[i] - a); y[i] = a
    return y * np.sin(np.pi * np.arange(n) / n) ** 2 * 0.9

def chime():
    s = sum(tone(midi(n), 1.5) * g for n, g in [(84, .5), (91, .3), (96, .2)])
    return reverb(s, 0.4) * 0.7

def save(name, x, encode=True):
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.85
    fade = int(SR * 1.0)
    if len(x) > 4 * fade: x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    st = np.repeat((x * 32767).astype(np.int16)[:, None], 2, axis=1)
    wav = os.path.join(OUT, name + ".wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
    if encode:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "64k", os.path.join(OUT, name + ".m4a")], check=True)
        os.remove(wav)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    save("music_guofeng_1", guofeng(1, root=62)); save("music_guofeng_2", guofeng(2, root=57))
    save("music_light_1", light(3, root=60)); save("music_light_2", light(4, root=65))
    save("sfx_whoosh", whoosh()); save("sfx_chime", chime())
    print("done:", sorted(os.listdir(OUT)))
