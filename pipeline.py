"""视频生成流水线：脚本 -> 图片 -> 配音 -> ffmpeg 合成。提供者可插拔（环境变量配置）。"""
import os, json, math, random, subprocess, base64, re, hashlib
import requests
from PIL import Image, ImageDraw, ImageFilter

FONT = os.getenv("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")
VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
BASE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720
STYLES = {
    "ink": "traditional Chinese ink-wash painting, muted monochrome with light red accents, rice paper texture, misty mountains",
    "kids": "warm colorful children's picture book illustration, soft watercolor, cute rounded characters",
}

# ---------------- 脚本 ----------------
BUILTIN = {
    "刻舟求剑": {"title": "刻舟求剑", "subtitle": "成语故事", "image_dir": "builtin/kezhouqiujian", "scenes": [
        {"narration": "战国时期，有个楚国人，带着一把心爱的宝剑，乘船渡江。", "image_prompt": "an ancient Chu man in robes standing on a wooden boat crossing a wide river, holding a sword"},
        {"narration": "船到江心，一不小心，宝剑从船边滑落，扑通一声掉进了水里。", "image_prompt": "a sword slipping off the side of a boat and splashing into the river, man reaching out in shock"},
        {"narration": "他不慌不忙，掏出小刀，在剑掉下去的船舷上刻了一个记号，说：剑就是从这儿掉下去的。", "image_prompt": "an old man carving a red mark on the boat's gunwale with a small knife"},
        {"narration": "船继续前行，终于靠了岸。", "image_prompt": "the wooden boat arriving at a reedy riverbank"},
        {"narration": "楚人顺着记号跳进水里找剑，可找了半天，什么也没找到。", "image_prompt": "the man in the water beside the docked boat searching under the mark, finding nothing"},
        {"narration": "船一直在走，剑却沉在原处。这个故事告诉我们：事物总在变化，不能死守老办法。", "image_prompt": "a sword resting on the riverbed far behind while the boat floats away, contemplative mood"},
    ]},
}

def template_script(topic, kind):
    if kind == "kepu":
        n = [f"你有没有想过：{topic}？今天我们就来聊一聊。",
             f"这个现象在生活中很常见，很多人每天都能遇到，却不知道背后的原因。",
             f"其实，答案藏在科学原理里。科学家通过观察和实验，一步步找到了解释。",
             f"简单来说，关于{topic}，关键在于自然规律在悄悄发挥作用。",
             f"了解了原理，我们就能更好地理解身边的世界，也能避免一些常见的误区。",
             f"保持好奇心，多问一个为什么，生活处处是科学。我们下期再见！"]
        sub = "生活常识科普"
    else:
        n = [f"今天我们来讲一个成语故事：{topic}。",
             f"很久很久以前，有一个人，遇到了一件看似平常的事情。",
             f"他用自己的办法去处理，自以为十分聪明。",
             f"可是事情的发展，并没有像他想的那样。",
             f"最后，人们从这件事里明白了一个道理，于是有了“{topic}”这个成语。",
             f"希望大家记住{topic}的故事，遇事多思考，做一个明白事理的人。"]
        sub = "成语故事"
    return {"title": topic, "subtitle": sub + "（模板脚本）",
            "scenes": [{"narration": x, "image_prompt": f"scene {i+1} illustrating '{topic}': {x}"} for i, x in enumerate(n)]}

def llm_script(topic, kind):
    base, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    what = "生活常识科普短视频" if kind == "kepu" else "成语故事短视频"
    prompt = (f"为“{topic}”写一个约60秒的{what}普通话旁白脚本，6个场景，每个场景旁白20-40字，"
              "最后一个场景点明道理/结论。同时为每个场景写一句英文画面描述（不要出现文字）。"
              '只输出JSON：{"title":"","subtitle":"","scenes":[{"narration":"","image_prompt":""}]}')
    r = requests.post(base.rstrip("/") + "/chat/completions", timeout=120,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    data = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    assert 3 <= len(data["scenes"]) <= 8
    data.setdefault("title", topic)
    return data

def get_script(topic, kind, log):
    if topic in BUILTIN:
        log("使用内置脚本"); return BUILTIN[topic], "builtin"
    if os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY"):
        try:
            log("调用大模型生成脚本"); return llm_script(topic, kind), "llm"
        except Exception as e:
            log(f"大模型失败，改用模板：{e}")
    return template_script(topic, kind), "template"

# ---------------- 图片 ----------------
def api_image(prompt, style, out):
    key = os.getenv("IMAGE_API_KEY")
    base = os.getenv("IMAGE_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("IMAGE_MODEL", "gpt-image-1")
    r = requests.post(base.rstrip("/") + "/images/generations", timeout=300,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "prompt": f"{prompt}. Style: {STYLES[style]}. 16:9 composition, no text, no letters.",
                            "size": os.getenv("IMAGE_SIZE", "1536x1024"), "n": 1})
    r.raise_for_status()
    d = r.json()["data"][0]
    raw = base64.b64decode(d["b64_json"]) if d.get("b64_json") else requests.get(d["url"], timeout=120).content
    open(out + ".src", "wb").write(raw)
    Image.open(out + ".src").convert("RGB").save(out)
    fit(out)

def fit(path):
    im = Image.open(path).convert("RGB"); s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)))
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im.crop((l, t, l + W, t + H)).save(path)

def procedural_image(seed, idx, n, style, out):
    """无 key 时的程序化占位图（水墨 / 绘本两种配色）。"""
    r = random.Random(seed)
    if style == "kids":
        bg, inkc, acc = (250, 240, 215), (90, 140, 120), (240, 130, 80)
    else:
        bg, inkc, acc = (236, 228, 210), (40, 40, 45), (175, 40, 30)
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    for _ in range(3000):
        x, y = r.randint(0, W - 1), r.randint(0, H - 1); c = r.randint(-12, 4)
        d.point((x, y), tuple(max(0, v + c) for v in bg))
    def ink(fn, blur, a, color=inkc):
        m = Image.new("L", (W, H), 0); fn(ImageDraw.Draw(m))
        m = m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * a)); im.paste(color, (0, 0), m)
    sx = r.randint(150, W - 150)
    ink(lambda dd: dd.ellipse([sx - 45, 90, sx + 45, 180], fill=255), 4, .6, acc)
    for layer, (a, b) in enumerate([(.2, 14), (.38, 7), (.55, 3)]):
        pts = [(0, H)]; x = 0; base = 330 + 70 * layer
        while x <= W + 100:
            pts.append((x, base - r.randint(0, 200) * (1 if r.random() > .4 else .35))); x += r.randint(50, 130)
        pts.append((W, H)); y0 = base + 130
        ink(lambda dd, p=pts: dd.polygon(p, fill=255), b, a)
    wm = Image.new("L", (W, H), 0); ImageDraw.Draw(wm).rectangle([0, 540, W, H], fill=215)
    im.paste(Image.new("RGB", (W, H), bg), (0, 0), wm.filter(ImageFilter.GaussianBlur(25)))
    def waves(dd):
        for _ in range(35):
            y = r.randint(550, H); x = r.randint(-100, W); dd.line([(x, y), (x + r.randint(60, 260), y)], fill=255, width=2)
    ink(waves, 1.2, .35)
    # 小舟/人物剪影，位置随场景推进
    cx = int(200 + (W - 400) * idx / max(1, n - 1)); cy = 600
    ink(lambda dd: (dd.polygon([(cx - 150, cy), (cx + 150, cy), (cx + 110, cy + 35), (cx - 110, cy + 35)], fill=255),
                    dd.ellipse([cx - 10, cy - 85, cx + 10, cy - 65], fill=255),
                    dd.polygon([(cx - 6, cy - 66), (cx + 6, cy - 66), (cx + 24, cy), (cx - 24, cy)], fill=255)), 1.5, .85)
    d = ImageDraw.Draw(im); d.rectangle([W - 90, 50, W - 50, 90], fill=acc)
    im.save(out)

def get_image(script, i, style, out, log):
    sc = script["scenes"][i]
    if script.get("image_dir") and style == "ink":
        p = os.path.join(BASE, script["image_dir"], f"img{i}.png")
        if os.path.exists(p):
            Image.open(p).convert("RGB").save(out); fit(out); return "builtin"
    if os.getenv("IMAGE_API_KEY"):
        try:
            api_image(sc["image_prompt"], style, out); return "api"
        except Exception as e:
            log(f"图片API失败，改用占位图：{e}")
    seed = int(hashlib.md5((script["title"] + str(i)).encode()).hexdigest()[:8], 16)
    procedural_image(seed, i, len(script["scenes"]), style, out); return "procedural"

# ---------------- 配音 & 合成 ----------------
def run(cmd): subprocess.run(cmd, check=True, capture_output=True)
def dur(f): return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True, check=True).stdout)

def tts(text, out):
    try:
        run(["python3", "-m", "edge_tts", "--voice", VOICE, "--rate=-10%", "--text", text, "--write-media", out]); return True
    except Exception:
        return False

def wrap(t, n=24):
    if len(t) <= n: return t
    k = math.ceil(len(t) / math.ceil(len(t) / n)); return "\n".join(t[i:i + k] for i in range(0, len(t), k))

def enc(): return ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2"]

def build(topic, kind, style, wd, out, progress):
    os.makedirs(wd, exist_ok=True); log = lambda m: progress(None, m)
    script, src = get_script(topic, kind, log)
    json.dump(script, open(f"{wd}/script.json", "w"), ensure_ascii=False, indent=1)
    n = len(script["scenes"]); total = 2 + n * 2; step = [1]
    def adv(m): step[0] += 1; progress(int(100 * step[0] / total), m)
    progress(int(100 / total), f"脚本完成（{src}），共{n}个场景")
    srcs = []
    for i in range(n):
        srcs.append(get_image(script, i, style, f"{wd}/img{i}.png", log)); adv(f"第{i+1}张图片完成（{srcs[-1]}）")
    bgc = "0xFAF0D7" if style == "kids" else "0xECE4D2"
    open(f"{wd}/title.txt", "w").write(script["title"]); open(f"{wd}/subt.txt", "w").write(script.get("subtitle", ""))
    has = tts(script["title"], f"{wd}/t.mp3")
    ain = ["-i", f"{wd}/t.mp3"] if has else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:d=4", *ain, "-vf",
         f"drawtext=fontfile={FONT}:textfile={wd}/title.txt:fontsize=120:fontcolor=0x28282d:x=(w-tw)/2:y=(h-th)/2-30,"
         f"drawtext=fontfile={FONT}:textfile={wd}/subt.txt:fontsize=38:fontcolor=0xaf281e:x=(w-tw)/2:y=h/2+100",
         "-af", "apad", "-t", "4", *enc(), f"{wd}/s_t.mp4"])
    segs = [f"{wd}/s_t.mp4"]; narr = has
    for i, sc in enumerate(script["scenes"]):
        a = f"{wd}/a{i}.mp3"; ok = tts(sc["narration"], a); narr = narr and ok
        d = (dur(a) if ok else max(4, len(sc["narration"]) * 0.25)) + 1.2; nf = int(d * 30)
        open(f"{wd}/sub{i}.txt", "w").write(wrap(sc["narration"]))
        ai = ["-i", a] if ok else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg", "-y", "-loop", "1", "-i", f"{wd}/img{i}.png", *ai, "-filter_complex",
             f"[0]scale=2560:1440,zoompan=z='1+0.12*on/{nf}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={nf}:s={W}x{H}:fps=30,"
             f"drawtext=fontfile={FONT}:textfile={wd}/sub{i}.txt:fontsize=36:fontcolor=white:borderw=3:bordercolor=0x202020:line_spacing=10:x=(w-tw)/2:y=h-th-40[v];[1]apad[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.2f}", *enc(), f"{wd}/s{i}.mp4"])
        segs.append(f"{wd}/s{i}.mp4"); adv(f"第{i+1}段配音与画面完成")
    open(f"{wd}/list.txt", "w").write("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{wd}/list.txt", "-c", "copy", "-movflags", "+faststart", out])
    return {"duration": round(dur(out), 1), "script_source": src, "image_sources": srcs, "narration": narr, "script": script}
