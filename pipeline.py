"""视频生成流水线：脚本 -> 图片 -> 配音 -> ffmpeg 合成。提供者可插拔（环境变量配置）。"""
import os, json, math, random, subprocess, base64, re, hashlib, time
import requests
from PIL import Image, ImageDraw, ImageFilter

FONT = os.getenv("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")
VOICE = os.getenv("TTS_VOICE", "Cherry")
BASE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720
STYLES = {
    "ink": "traditional Chinese ink-wash painting, muted monochrome with light red accents, rice paper texture, misty mountains",
    "kids": "warm colorful children's picture book illustration, soft watercolor, cute rounded characters",
}

# ---------------- 脚本 ----------------
BUILTIN = {
    "刻舟求剑": {
        "title": "刻舟求剑", "subtitle": "成语故事", "image_dir": "builtin/kezhouqiujian",
        "publish_info": {
            "title": "刻舟求剑在物理学上到底错在哪个运动参照系？",
            "description": "古人乘船渡江剑落水中，在船舷刻记号真能找到剑吗？用现代物理经典力学的运动参照系与流体力学深度拆解！关注我，每天看懂一个硬核成语典故。",
            "tags": ["#刻舟求剑", "#成语物理学", "#运动参照系", "#硬核国学", "#经典力学", "#原来如此"]
        },
        "scenes": [
            {"narration": "战国时期，有个楚国人，带着一把心爱的宝剑，乘船渡江。", "image_prompt": "an ancient Chu man in robes standing on a wooden boat crossing a wide river, holding a sword"},
            {"narration": "船到江心，一不小心，宝剑从船边滑落，扑通一声掉进了水里。", "image_prompt": "a sword slipping off the side of a boat and splashing into the river, man reaching out in shock"},
            {"narration": "他不慌不忙，掏出小刀，在剑掉下去的船舷上刻了一个记号，说：剑就是从这儿掉下去的。", "image_prompt": "an old man carving a red mark on the boat's gunwale with a small knife"},
            {"narration": "船继续前行，终于靠了岸。", "image_prompt": "the wooden boat arriving at a reedy riverbank"},
            {"narration": "楚人顺着记号跳进水里找剑，可找了半天，什么也没找到。", "image_prompt": "the man in the water beside the docked boat searching under the mark, finding nothing"},
            {"narration": "船一直在走，剑却沉在原处。这个故事告诉我们：事物总在变化，不能死守老办法。", "image_prompt": "a sword resting on the riverbed far behind while the boat floats away, contemplative mood"},
        ]
    },
}

def template_script(topic, kind):
    """无 key 时的模板脚本兜底。"""
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
    """调用大模型（qwen-plus）根据主题生成分镜剧本与专属抖音发布物料（标题、描述、话题标签）。"""
    base, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    what = "生活常识科普短视频" if kind == "kepu" else "成语故事短视频"

    if kind == "chengyu":
        style_guide = (
            "【古风传统水墨画风格约束（严禁现代或卡通风，必须如经典中国古代水墨长卷）】：\n"
            "1. 严格统一为传统中国古典写意水墨画意境（traditional Chinese ink-wash painting style, elegant ancient Chinese landscape, misty mountains and wide river, muted monochrome ink tones with subtle warm paper tint, rice paper texture, cinematic poetic atmosphere）；\n"
            "2. 人物必须身着古代汉服长袍、乘一叶扁舟或漫步于松石云海之间，画面充满东方诗意美学与哲思，严禁出现任何现代元素、现代服饰或工业机器；\n"
            "3. 严禁出现暴力、血腥或易触发AI审核拦截的负面敏感词汇；\n"
            "4. 画面构图 16:9，画面中严禁出现任何英文字母、文字、印章文字或水印。"
        )
    else:
        style_guide = (
            "【温馨儿童绘本卡通风格约束】：\n"
            "1. 严格统一为温馨可爱的全年龄儿童绘本卡通风格（cute colorful 2D storybook illustration, lively characters, soft lighting）；\n"
            "2. 严禁出现任何人体微距特写、皮肤纹理皱褶、解剖组织、血管、病理水泡、肿胀等易触发百炼内容安全审核拦截(DataInspectionFailed)的词汇（严禁使用 skin, wrinkled, swelling, naked, bath, body, vein 等词）；\n"
            "3. 一律采用可爱的卡通拟人化角色、活泼小动物或趣味科普道具实验（如戴着小泳帽的可爱卡通小男孩在浴室地毯上好奇打量橡胶小鸭）来寓意科学原理，确保百炼图文安全审核 100% 顺利通过；\n"
            "4. 画面构图 16:9，严禁画面出现任何英文字母、文字或水印。"
        )

    prompt = (f"为“{topic}”写一个约60秒的{what}普通话旁白脚本，6个场景，每个场景旁白20-40字，"
              "最后一个场景点明核心科学原理或哲理道理。\n"
              f"【AI画面生成约束（极为重要）】：同时为每个场景写一句英文画面描述（image_prompt），专用于百炼AI绘图：\n{style_guide}\n"
              "另外，必须为本期主题量身定制专属的抖音发布物料（杜绝千篇一律的套话！严禁使用固定模板）：\n"
              "1. 爆款标题：必须针对本主题，带悬念或趣味，严禁超过30字；\n"
              "2. 作品描述：50-80字深度结合本期具体科学原理或故事看点，通俗生动；\n"
              "3. 话题标签：5个与本主题高度相关的热门标签（如 #具体主题 #科学原理 等）。\n"
              '只输出JSON：{"title":"","subtitle":"","publish_info":{"title":"","description":"","tags":["#标签1","#标签2"]},"scenes":[{"narration":"","image_prompt":""}]}')
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
def qwen_image(prompt, style, out):
    """通义千问生图（qwen-image-2.0）：调用 DashScope 多模态生成接口同步生成 1280x720 图片。"""
    base = os.getenv("IMAGE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    key = os.getenv("IMAGE_API_KEY")
    model = os.getenv("IMAGE_MODEL", "qwen-image-2.0")
    watermark = os.getenv("IMAGE_WATERMARK", "false").lower() == "true"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": f"{prompt}. Style: {STYLES[style]}. 16:9 composition, no text, no letters."}]}
            ]
        },
        "parameters": {
            "size": os.getenv("IMAGE_SIZE", "1280*720"),
            "n": 1,
            "watermark": watermark
        }
    }
    r = requests.post(f"{base}/services/aigc/multimodal-generation/generation", headers=headers, json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"qwen-image 生成失败: {r.status_code} {r.text}")
    data = r.json()
    img_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
    raw = requests.get(img_url, timeout=60).content
    save_image(raw, out)

def api_image(prompt, style, out):
    """OpenAI 兼容生图接口：调用 /images/generations 接口生成图片。"""
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
    save_image(raw, out)

def wanx_image(prompt, style, out):
    """通义万相文生图（DashScope 异步协议，适用 wan2.5 及以下模型）：提交任务 -> 轮询结果 -> 下载并裁切为 1280x720。"""
    base = os.getenv("IMAGE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    h = {"Authorization": f"Bearer {os.getenv('IMAGE_API_KEY')}"}
    r = requests.post(base + "/services/aigc/text2image/image-synthesis", timeout=60,
                      headers={**h, "X-DashScope-Async": "enable"},
                      json={"model": os.getenv("IMAGE_MODEL", "wan2.2-t2i-flash"),
                            "input": {"prompt": f"{prompt}. Style: {STYLES[style]}. 16:9 composition, no text, no letters.",
                                      "negative_prompt": "文字, 字母, 水印, 低质量, 肢体畸形"},
                            "parameters": {"size": os.getenv("IMAGE_SIZE", "1440*810"), "n": 1}})
    if not r.ok: raise RuntimeError(f"万相提交失败：{r.text}")
    tid = r.json()["output"]["task_id"]
    for _ in range(100):  # 最多约 5 分钟
        time.sleep(3)
        o = requests.get(f"{base}/tasks/{tid}", headers=h, timeout=30).json()["output"]
        if o["task_status"] == "SUCCEEDED":
            return save_image(requests.get(o["results"][0]["url"], timeout=120).content, out)
        if o["task_status"] in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"万相任务失败：{o.get('code')} {o.get('message')}")
    raise TimeoutError("万相任务超时")

def save_image(raw, out):
    """保存接口返回的原图，转为 RGB 并裁切到视频尺寸。"""
    open(out + ".src", "wb").write(raw)
    Image.open(out + ".src").convert("RGB").save(out)
    fit(out)

def fit(path):
    """等比例放大并居中裁剪图片为标准视频分辨率。"""
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

def sanitize_prompt_via_llm(orig_prompt, topic, style="kids"):
    """调用通义千问大模型（qwen-plus）将可能触发安全风控的提示词智能重构为全年龄合规的古风水墨或绘本插画描述。"""
    base, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "qwen-plus")
    if style == "ink":
        fallback = f"Traditional Chinese ink-wash painting of ancient scenery related to {topic}, elegant mountains and river, rice paper texture, poetic artistic mood, no text"
        system_guide = (
            "You are an expert prompt engineer. Rewrite the provided prompt into a safe, traditional Chinese ink-wash painting style "
            "(muted monochrome, rice paper texture, ancient robes and poetic misty scenery, no modern elements, no violence). "
            "Return ONLY the rewritten English prompt text without quotes or explanations."
        )
    else:
        fallback = f"A lovely 2D cartoon picture book illustration about {topic}, cute character, bright cheerful scene, storybook art style, no text"
        system_guide = (
            "You are an expert prompt engineer. Rewrite the provided image prompt into a safe, cheerful, family-friendly "
            "2D cartoon picture book illustration prompt. Strictly remove any human skin, medical terms, wrinkles, swelling, "
            "body anatomy, or sensitive words that might trigger AI content filters. Keep it cute and colorful. "
            "Return ONLY the rewritten English prompt text without quotes or explanations."
        )

    if not (base and key):
        return fallback

    try:
        r = requests.post(base.rstrip("/") + "/chat/completions", timeout=30,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": [
                              {"role": "system", "content": system_guide},
                              {"role": "user", "content": f"Topic: {topic}. Original prompt: {orig_prompt}"}
                          ], "temperature": 0.5})
        if r.ok:
            content = r.json()["choices"][0]["message"]["content"].strip()
            if content:
                return content
    except Exception:
        pass
    return fallback

def get_image(script, i, style, out, log):
    """获取场景配图：优先内置图片，若配置了API则全部调用百炼接口真实生成，具备智能安全净化重试机制（严禁退化为简图）。"""
    sc = script["scenes"][i]
    topic = script.get("title", "成语" if style == "ink" else "科普")
    if script.get("image_dir") and style == "ink":
        p = os.path.join(BASE, script["image_dir"], f"img{i}.png")
        if os.path.exists(p):
            Image.open(p).convert("RGB").save(out)
            fit(out)
            return "builtin"

    if os.getenv("IMAGE_API_KEY"):
        provider = os.getenv("IMAGE_PROVIDER", "qwen" if "qwen" in os.getenv("IMAGE_MODEL", "") else "openai")
        dispatch = {
            "qwen": lambda p: qwen_image(p, style, out),
            "wanx": lambda p: wanx_image(p, style, out),
            "openai": lambda p: api_image(p, style, out),
        }
        gen_fn = dispatch.get(provider, lambda p: qwen_image(p, style, out))

        curr_prompt = sc["image_prompt"]
        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                gen_fn(curr_prompt)
                return "api"
            except Exception as e:
                last_error = e
                log(f"第{i+1}张分镜百炼生图第{attempt}次遇到异常: {e}")
                if attempt == 1:
                    log(f"正在调用大模型为第{i+1}张分镜重构合规的提示词...")
                    curr_prompt = sanitize_prompt_via_llm(sc["image_prompt"], topic, style)
                elif attempt == 2:
                    if style == "ink":
                        log(f"启用第{i+1}张分镜的传统中国古风水墨保底提示词重试百炼生图...")
                        curr_prompt = (
                            f"Masterpiece traditional Chinese ink-wash painting illustrating scene {i + 1} of '{topic}', "
                            f"classical Chinese ancient landscape, graceful scholar in robes, muted ink tones, "
                            f"rice paper texture, misty mountains, artistic tranquility, 16:9 composition, no text, no letters"
                        )
                    else:
                        log(f"启用第{i+1}张分镜的主题级高容错儿童绘本提示词重试百炼生图...")
                        curr_prompt = (
                            f"A heartwarming educational 2D storybook cartoon illustration about {topic}, "
                            f"scene {i + 1}, cute friendly cartoon character explaining science, "
                            f"bright cozy colors, clean background, highly detailed, no text, no letters"
                        )
                time.sleep(2)

        # 多次重试仍失败则抛出异常，坚决不静默降级为水墨简图
        raise RuntimeError(f"第{i+1}张分镜调用百炼生图失败，已重试{max_attempts}次: {last_error}")

    # 仅在完全没有配置生图 API 密钥时作为演示兜底
    seed = int(hashlib.md5((script["title"] + str(i)).encode()).hexdigest()[:8], 16)
    procedural_image(seed, i, len(script["scenes"]), style, out)
    return "procedural"

# ---------------- 配音 & 合成 ----------------
def run(cmd):
    """执行外部命令行工具，捕获异常输出。"""
    subprocess.run(cmd, check=True, capture_output=True)

def dur(f):
    """使用 ffprobe 获取音频或视频文件的时长（秒）。"""
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True, check=True).stdout)

def qwen_tts(text, out):
    """通义千问语音合成（qwen3-tts-flash）：调用 DashScope 多模态接口生成音频。"""
    key = os.getenv("TTS_API_KEY") or os.getenv("IMAGE_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        return False
    model = os.getenv("VOICE_MODEL", "qwen3-tts-flash")
    voice = os.getenv("TTS_VOICE", "Cherry")
    base = os.getenv("TTS_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "input": {"text": text},
        "parameters": {"voice": voice, "language_type": "Chinese"}
    }
    r = requests.post(f"{base}/services/aigc/multimodal-generation/generation", headers=headers, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"qwen-tts 失败: {r.status_code} {r.text}")
    res = r.json()
    audio_url = res.get("output", {}).get("audio", {}).get("url")
    if audio_url:
        resp = requests.get(audio_url, timeout=60)
        open(out, "wb").write(resp.content)
        return True
    return False

def tts(text, out):
    """旁白配音：优先尝试通义 qwen3-tts-flash，回退至 edge-tts。"""
    tts_provider = os.getenv("TTS_PROVIDER", "qwen")
    attempts = [
        lambda: qwen_tts(text, out) if tts_provider == "qwen" else False,
        lambda: (run(["python3", "-m", "edge_tts", "--voice", os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural"), "--rate=-10%", "--text", text, "--write-media", out]) is None or True),
    ]
    for attempt in attempts:
        try:
            if attempt():
                return True
        except Exception:
            continue
    return False

def wrap(t, n=24):
    """对长旁白文本进行按字数折行处理。"""
    if len(t) <= n: return t
    k = math.ceil(len(t) / math.ceil(len(t) / n)); return "\n".join(t[i:i + k] for i in range(0, len(t), k))

def layout_title_and_subtitle(title, subtitle):
    """根据主标题与副标题自适应计算折行文本、字号、行距与纵向坐标，确保文字绝不溢出 1280x720 屏幕。"""
    t = (title or "").strip()
    length = len(t)
    if length <= 8:
        # 短标题：单行，大气醒目
        fmt_title = t
        t_size = 76
        t_space = 15
        t_y = "(h-th)/2-45"
    elif length <= 13:
        # 中等长度标题：单行
        fmt_title = t
        t_size = 58
        t_space = 15
        t_y = "(h-th)/2-45"
    elif length <= 24:
        # 较长标题：优雅均分折为两行
        mid = math.ceil(length / 2)
        # 1. 优先在常见标点符号处折行
        puncs = ["？", "?", "！", "!", "，", ",", "：", "、", " "]
        split_pos = -1
        for p in puncs:
            pos = t.rfind(p, 0, mid + 4)
            if pos >= 4 and pos > split_pos:
                split_pos = pos + 1
        # 2. 若无标点，优先在常见虚词/连词（了、时、后、中、里、的）后自然断句
        if split_pos == -1:
            for c in ["了", "时", "后", "中", "里", "的"]:
                pos = t.rfind(c, max(4, mid - 4), mid + 3)
                if pos != -1 and pos >= split_pos:
                    split_pos = pos + 1
        if split_pos == -1:
            split_pos = mid
        fmt_title = f"{t[:split_pos].strip()}\n{t[split_pos:].strip()}"
        t_size = 46
        t_space = 18
        t_y = "(h-th)/2-55"
    else:
        # 超长标题：每行最多 12~13 字换行，最多 3 行
        lines = [t[i:i + 13] for i in range(0, min(length, 39), 13)]
        fmt_title = "\n".join(lines)
        t_size = 38
        t_space = 16
        t_y = "(h-th)/2-65"

    sub = (subtitle or "").strip()
    sub_len = len(sub)
    if sub_len <= 18:
        fmt_sub = sub
        s_size = 34
        s_space = 10
        s_y = "h/2+80"
    else:
        # 副标题智能断句折为两行
        sub_mid = math.ceil(sub_len / 2)
        sub_puncs = ["，", ",", "、", " ", "！", "!", "？", "?"]
        sub_split = -1
        for p in sub_puncs:
            pos = sub.rfind(p, max(6, sub_mid - 6), sub_mid + 5)
            if pos != -1 and pos > sub_split:
                sub_split = pos + 1
        if sub_split == -1:
            sub_split = sub_mid
        fmt_sub = f"{sub[:sub_split].strip()}\n{sub[sub_split:].strip()}"
        s_size = 28
        s_space = 12
        s_y = "h/2+75"

    return fmt_title, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y

def enc():
    """返回标准 ffmpeg 视频输出编码参数列表。"""
    return ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2"]

def build(topic, kind, style, wd, out, progress):
    """流水线生成主函数：负责脚本、生图、配音与最终视频合成。"""
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

    fmt_title, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y = layout_title_and_subtitle(
        script.get("title", topic), script.get("subtitle", "")
    )
    open(f"{wd}/title.txt", "w", encoding="utf-8").write(fmt_title)
    open(f"{wd}/subt.txt", "w", encoding="utf-8").write(fmt_sub)

    has = tts(script.get("title", topic), f"{wd}/t.mp3")
    ain = ["-i", f"{wd}/t.mp3"] if has else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:d=4", *ain, "-vf",
         f"drawtext=fontfile={FONT}:textfile={wd}/title.txt:fontsize={t_size}:fontcolor=0x28282d:line_spacing={t_space}:expansion=none:x=(w-tw)/2:y={t_y},"
         f"drawtext=fontfile={FONT}:textfile={wd}/subt.txt:fontsize={s_size}:fontcolor=0xaf281e:line_spacing={s_space}:expansion=none:x=(w-tw)/2:y={s_y}",
         "-af", "apad", "-t", "4", *enc(), f"{wd}/s_t.mp4"])
    segs = [f"{wd}/s_t.mp4"]; narr = has
    for i, sc in enumerate(script["scenes"]):
        a = f"{wd}/a{i}.mp3"; ok = tts(sc["narration"], a); narr = narr and ok
        d = (dur(a) if ok else max(4, len(sc["narration"]) * 0.25)) + 1.2; nf = int(d * 30)
        open(f"{wd}/sub{i}.txt", "w", encoding="utf-8").write(wrap(sc["narration"]))
        ai = ["-i", a] if ok else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg", "-y", "-loop", "1", "-i", f"{wd}/img{i}.png", *ai, "-filter_complex",
             f"[0]scale=2560:1440,zoompan=z='1+0.12*on/{nf}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={nf}:s={W}x{H}:fps=30,"
             f"drawtext=fontfile={FONT}:textfile={wd}/sub{i}.txt:fontsize=36:fontcolor=white:borderw=3:bordercolor=0x202020:line_spacing=10:expansion=none:x=(w-tw)/2:y=h-th-40[v];[1]apad[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.2f}", *enc(), f"{wd}/s{i}.mp4"])
        segs.append(f"{wd}/s{i}.mp4"); adv(f"第{i+1}段配音与画面完成")
    open(f"{wd}/list.txt", "w", encoding="utf-8").write("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{wd}/list.txt", "-c", "copy", "-movflags", "+faststart", out])
    return {"duration": round(dur(out), 1), "script_source": src, "image_sources": srcs, "narration": narr, "script": script}
