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
# ---------------- 脚本 ----------------
BUILTIN = {
    "刻舟求剑": {
        "title": "刻舟求剑", "subtitle": "成语故事", "image_dir": "builtin/kezhouqiujian",
        "title_en": "Marking the Boat to Find the Sword",
        "subtitle_en": "Ancient Chinese Wisdom & Classical Physics",
        "publish_info": {
            "title": "刻舟求剑在物理学上到底错在哪个运动参照系？",
            "description": "古人乘船渡江剑落水中，在船舷刻记号真能找到剑吗？用现代物理经典力学的运动参照系与流体力学深度拆解！关注我，每天看懂一个硬核成语典故。",
            "tags": ["#刻舟求剑", "#成语物理学", "#运动参照系", "#硬核国学", "#经典力学", "#原来如此"]
        },
        "publish_info_en": {
            "title": "Why Marking a Moving Boat Won't Save Your Dropped Sword",
            "description": "A ferry passenger dropped his sword into a rushing river and carved a notch on the boat to mark the spot. An ancient lesson on shifting reference frames and changing worlds! Follow for daily wisdom.",
            "tags": ["#ChineseIdiom", "#Philosophy", "#PhysicsFun", "#LearnOnTikTok", "#AncientWisdom"]
        },
        "scenes": [
            {
                "narration": "战国时期，有个楚国人，带着一把心爱的宝剑，乘船渡江。",
                "narration_en": "During the Warring States period, a man crossed a wide river on a ferry, holding his prized sword.",
                "image_prompt": "an ancient Chu man in robes standing on a wooden boat crossing a wide river, holding a sword"
            },
            {
                "narration": "船到江心，一不小心，宝剑从船边滑落，扑通一声掉进了水里。",
                "narration_en": "Midway across the river, his hand slipped, and the sword splashed into the rushing water.",
                "image_prompt": "a sword slipping off the side of a boat and splashing into the river, man reaching out in shock"
            },
            {
                "narration": "他不慌不忙，掏出小刀，在剑掉下去的船舷上刻了一个记号，说：剑就是从这儿掉下去的。",
                "narration_en": "Calmly, he pulled out a knife and carved a notch on the boat's side: 'This is where it fell.'",
                "image_prompt": "an old man carving a red mark on the boat's gunwale with a small knife"
            },
            {
                "narration": "船继续前行，终于靠了岸。",
                "narration_en": "The boat sailed on smoothly and finally arrived at the distant shore.",
                "image_prompt": "the wooden boat arriving at a reedy riverbank"
            },
            {
                "narration": "楚人顺着记号跳进水里找剑，可找了半天，什么也没找到。",
                "narration_en": "He jumped into the water beneath the notch, searching eagerly, but found nothing.",
                "image_prompt": "the man in the water beside the docked boat searching under the mark, finding nothing"
            },
            {
                "narration": "船一直在走，剑却沉在原处。这个故事告诉我们：事物总在变化，不能死守老办法。",
                "narration_en": "The boat kept moving while the sword stayed behind. Wisdom tells us: adapt as conditions change.",
                "image_prompt": "a sword resting on the riverbed far behind while the boat floats away, contemplative mood"
            },
        ]
    },
}

def template_script(topic, kind):
    """无 key 时的模板脚本兜底（同时提供中文与地道英文版本）。"""
    if kind == "kepu":
        n = [f"你有没有想过：{topic}？今天我们就来聊一聊。",
             f"这个现象在生活中很常见，很多人每天都能遇到，却不知道背后的原因。",
             f"其实，答案藏在科学原理里。科学家通过观察和实验，一步步找到了解释。",
             f"简单来说，关于{topic}，关键在于自然规律在悄悄发挥作用。",
             f"了解了原理，我们就能更好地理解身边的世界，也能避免一些常见的误区。",
             f"保持好奇心，多问一个为什么，生活处处是科学。我们下期再见！"]
        n_en = [
            f"Have you ever wondered about: {topic}? Let us explore it today.",
            "This phenomenon is everywhere in daily life, yet few know the science behind it.",
            "The truth lies in nature's laws, discovered through keen observation and experiments.",
            f"In simple terms, understanding {topic} reveals how science works quietly around us.",
            "Knowing this helps us appreciate the world and avoid common misconceptions.",
            "Stay curious, keep exploring, and see you in the next episode!"
        ]
        sub = "生活常识科普"
        sub_en = "Daily Science Facts"
    else:
        n = [f"今天我们来讲一个成语故事：{topic}。",
             f"很久很久以前，有一个人，遇到了一件看似平常的事情。",
             f"他用自己的办法去处理，自以为十分聪明。",
             f"可是事情的发展，并没有像他想的那样。",
             f"最后，人们从这件事里明白了一个道理，于是有了“{topic}”这个成语。",
             f"希望大家记住{topic}的故事，遇事多思考，做一个明白事理的人。"]
        n_en = [
            f"Today, let us explore the classic story behind: {topic}.",
            "Long ago, someone encountered what seemed to be a simple everyday situation.",
            "He handled it in his own clever way, convinced he had found the perfect answer.",
            "However, reality unfolded quite differently from what he expected.",
            f"Eventually, people drew a lasting lesson from this, creating the idiom: {topic}.",
            "Remember this ancient wisdom: think flexibly and adapt to changing times."
        ]
        sub = "成语故事"
        sub_en = "Classic Idiom Story"

    return {
        "title": topic,
        "subtitle": sub + "（模板脚本）",
        "title_en": f"The Science of {topic}" if kind == "kepu" else f"The Story of {topic}",
        "subtitle_en": sub_en,
        "publish_info": {
            "title": f"揭秘：{topic}背后原来藏着这样的玄机！",
            "description": f"关于【{topic}】，生活里到底藏着怎样有趣的科学与哲理？用生动动画为您讲懂身边奇妙世界。关注我，每天学点硬核新知！",
            "tags": [f"#{topic}", "#原来如此", "#科普", "#涨知识", "#冷知识"]
        },
        "publish_info_en": {
            "title": f"Mind-Blowing Truth About {topic} Explained!",
            "description": f"Ever wondered what really happens with {topic}? Here is the fascinating science and story behind it. Follow for daily science bites!",
            "tags": ["#ScienceFacts", "#DidYouKnow", "#LearnOnTikTok", "#Educational", "#StoryTime"]
        },
        "scenes": [
            {
                "narration": x,
                "narration_en": n_en[i],
                "image_prompt": f"scene {i+1} illustrating '{topic}': {x}"
            } for i, x in enumerate(n)
        ]
    }

def llm_script(topic, kind):
    """调用大模型（qwen-plus）根据主题生成对齐的中英文分镜剧本与专属双语发布物料（抖音+TikTok）。"""
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

    prompt = (f"为“{topic}”写一个约60秒的{what}旁白脚本，要求同时输出完整地道的【中文版本】与【英文版本（用于TikTok出海）】：\n"
              "1. 包含6个场景，每个场景写一句中文旁白（20-40字）和对应的地道纯正英文旁白（narration_en，15-25个单词）；\n"
              "2. 最后一个场景点明核心科学原理或哲理道理；\n"
              f"3. 【AI画面生成约束（极为重要）】：同时为每个场景写一句英文画面描述（image_prompt），专用于百炼AI绘图：\n{style_guide}\n"
              "4. 必须同时定制专属的【抖音中文发布物料】与【TikTok英文发布物料】：\n"
              "   - publish_info（中文）：爆款标题（<=30字）、通俗看点描述（50-80字）、5个中文热门标签；\n"
              "   - publish_info_en（英文）：Viral TikTok Title (<=60字符)、Engaging Description (40-60 words)、5个热门英文标签（如 #LearnOnTikTok #ScienceFacts 等）。\n"
              '只输出JSON：{"title":"","subtitle":"","title_en":"","subtitle_en":"","publish_info":{"title":"","description":"","tags":["#标签1","#标签2"]},"publish_info_en":{"title":"","description":"","tags":["#Tag1","#Tag2"]},"scenes":[{"narration":"","narration_en":"","image_prompt":""}]}')
    r = requests.post(base.rstrip("/") + "/chat/completions", timeout=120,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    data = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    assert 3 <= len(data["scenes"]) <= 8
    data.setdefault("title", topic)
    data.setdefault("title_en", topic)
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

def qwen_tts(text, out, lang="zh"):
    """通义千问语音合成（qwen3-tts-flash）：调用 DashScope 多模态接口生成音频，支持中文与英文。"""
    key = os.getenv("TTS_API_KEY") or os.getenv("IMAGE_API_KEY") or os.getenv("LLM_API_KEY")
    if not key:
        return False
    model = os.getenv("VOICE_MODEL", "qwen3-tts-flash")
    voice = os.getenv("TTS_VOICE", "Cherry")
    lang_type = "English" if lang == "en" else "Chinese"
    base = os.getenv("TTS_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "input": {"text": text},
        "parameters": {"voice": voice, "language_type": lang_type}
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

def tts(text, out, lang="zh"):
    """旁白配音：优先尝试通义 qwen3-tts-flash，回退至 edge-tts（支持中文与英文出海原声）。"""
    tts_provider = os.getenv("TTS_PROVIDER", "qwen")
    default_edge_voice = "en-US-JennyNeural" if lang == "en" else os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    attempts = [
        lambda: qwen_tts(text, out, lang=lang) if tts_provider == "qwen" else False,
        lambda: (run(["python3", "-m", "edge_tts", "--voice", default_edge_voice, "--rate=-5%", "--text", text, "--write-media", out]) is None or True),
    ]
    for attempt in attempts:
        try:
            if attempt():
                return True
        except Exception:
            continue
    return False

def wrap_narration(t, lang="zh"):
    """对旁白文本进行智能折行：中文按字数折行，英文按词组边界折行。"""
    if not t: return ""
    if lang == "en":
        import textwrap
        lines = textwrap.wrap(t, width=44)
        return "\n".join(lines[:3])
    else:
        if len(t) <= 24: return t
        k = math.ceil(len(t) / math.ceil(len(t) / 24))
        return "\n".join(t[i:i + k] for i in range(0, len(t), k))

def wrap(t, n=24):
    """兼容旧版中文旁白折行函数。"""
    return wrap_narration(t, lang="zh")

def layout_title_en(title, subtitle):
    """根据英文主标题与副标题自适应计算折行文本、字号、行距与纵向坐标，确保文字绝不溢出 1280x720 屏幕。"""
    import textwrap
    t = (title or "").strip()
    words = t.split()
    if len(words) <= 5:
        fmt_title = t
        t_size = 64
        t_space = 16
        t_y = "(h-th)/2-40"
    elif len(words) <= 10:
        lines = textwrap.wrap(t, width=32)
        fmt_title = "\n".join(lines[:2])
        t_size = 48
        t_space = 16
        t_y = "(h-th)/2-50"
    else:
        lines = textwrap.wrap(t, width=36)
        fmt_title = "\n".join(lines[:3])
        t_size = 38
        t_space = 14
        t_y = "(h-th)/2-60"

    sub = (subtitle or "").strip()
    if sub:
        sub_lines = textwrap.wrap(sub, width=48)
        fmt_sub = "\n".join(sub_lines[:2])
    else:
        fmt_sub = ""
    s_size = 28
    s_space = 10
    s_y = "h/2+75"

    return fmt_title, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y

def layout_title_and_subtitle(title, subtitle):
    """根据中文主标题与副标题自适应计算折行文本、字号、行距与纵向坐标，确保文字绝不溢出 1280x720 屏幕。"""
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

def render_single_video(script, lang, wd, out_video, style, bgc, adv_fn, log):
    """根据指定语言渲染独立视频版本（纯中文版或纯英文出海版），插画复用已有图片。"""
    is_en = (lang == "en")
    lang_tag = "en" if is_en else "zh"
    prefix = "【英文出海版】" if is_en else "【中文版】"
    log(f"开始压制{prefix}成片...")

    # 1. 标题卡处理
    if is_en:
        t_val = script.get("title_en") or script.get("title", "")
        s_val = script.get("subtitle_en") or script.get("subtitle", "")
        fmt_t, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y = layout_title_en(t_val, s_val)
    else:
        t_val = script.get("title", "")
        s_val = script.get("subtitle", "")
        fmt_t, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y = layout_title_and_subtitle(t_val, s_val)

    title_file = f"{wd}/title_{lang_tag}.txt"
    subt_file = f"{wd}/subt_{lang_tag}.txt"
    open(title_file, "w", encoding="utf-8").write(fmt_t)
    open(subt_file, "w", encoding="utf-8").write(fmt_sub)

    t_audio = f"{wd}/t_{lang_tag}.mp3"
    has_t = tts(t_val, t_audio, lang=lang)
    ain = ["-i", t_audio] if has_t else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:d=4", *ain, "-vf",
         f"drawtext=fontfile={FONT}:textfile={title_file}:fontsize={t_size}:fontcolor=0x28282d:line_spacing={t_space}:expansion=none:x=(w-tw)/2:y={t_y},"
         f"drawtext=fontfile={FONT}:textfile={subt_file}:fontsize={s_size}:fontcolor=0xaf281e:line_spacing={s_space}:expansion=none:x=(w-tw)/2:y={s_y}",
         "-af", "apad", "-t", "4", *enc(), f"{wd}/s_t_{lang_tag}.mp4"])

    segs = [f"{wd}/s_t_{lang_tag}.mp4"]
    narr_ok = has_t

    # 2. 分镜画面合成
    sub_fontsize = 30 if is_en else 36
    for i, sc in enumerate(script["scenes"]):
        narration_text = sc.get("narration_en") if is_en else sc.get("narration")
        if not narration_text:
            narration_text = sc.get("narration", "")

        a_file = f"{wd}/a{i}_{lang_tag}.mp3"
        ok = tts(narration_text, a_file, lang=lang)
        narr_ok = narr_ok and ok
        d = (dur(a_file) if ok else max(4, len(narration_text.split() if is_en else narration_text) * (0.35 if is_en else 0.25))) + 1.2
        nf = int(d * 30)

        sub_file = f"{wd}/sub{i}_{lang_tag}.txt"
        open(sub_file, "w", encoding="utf-8").write(wrap_narration(narration_text, lang=lang))
        ai = ["-i", a_file] if ok else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg", "-y", "-loop", "1", "-i", f"{wd}/img{i}.png", *ai, "-filter_complex",
             f"[0]scale=2560:1440,zoompan=z='1+0.12*on/{nf}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={nf}:s={W}x{H}:fps=30,"
             f"drawtext=fontfile={FONT}:textfile={sub_file}:fontsize={sub_fontsize}:fontcolor=white:borderw=3:bordercolor=0x202020:line_spacing=10:expansion=none:x=(w-tw)/2:y=h-th-40[v];[1]apad[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.2f}", *enc(), f"{wd}/s{i}_{lang_tag}.mp4"])
        segs.append(f"{wd}/s{i}_{lang_tag}.mp4")
        adv_fn(f"{prefix}第{i+1}段配音与画面完成")

    # 3. 拼接输出
    list_file = f"{wd}/list_{lang_tag}.txt"
    open(list_file, "w", encoding="utf-8").write("".join(f"file '{s}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-movflags", "+faststart", out_video])
    return round(dur(out_video), 1), narr_ok

def build(topic, kind, style, wd, out, progress, lang_mode="both"):
    """流水线生成主函数：负责脚本、生图、配音与最终视频合成（支持中文版、英文出海版或双版本同时生成）。"""
    os.makedirs(wd, exist_ok=True); log = lambda m: progress(None, m)
    script, src = get_script(topic, kind, log)
    json.dump(script, open(f"{wd}/script.json", "w"), ensure_ascii=False, indent=1)
    n = len(script["scenes"])

    do_cn = (lang_mode in ("both", "cn"))
    do_en = (lang_mode in ("both", "en"))
    total_phases = (1 if do_cn else 0) + (1 if do_en else 0)
    total_steps = 2 + n + (n * total_phases)
    step = [1]
    def adv(m):
        step[0] += 1
        progress(int(100 * step[0] / total_steps), m)

    progress(int(100 / total_steps), f"中英文双语剧本生成完成（{src}），共{n}个场景")

    # 1. 高清分镜插画生成（中英文版本 100% 共享画面，极大节约 API 资源与耗时）
    srcs = []
    for i in range(n):
        srcs.append(get_image(script, i, style, f"{wd}/img{i}.png", log))
        adv(f"第{i+1}张插画生成完成（{srcs[-1]}）")

    bgc = "0xFAF0D7" if style == "kids" else "0xECE4D2"

    dur_cn, narr_cn = 0, False
    dur_en, narr_en = 0, False
    out_en = os.path.splitext(out)[0] + "_en.mp4"

    # 2. 中文版视频压制
    if do_cn:
        dur_cn, narr_cn = render_single_video(script, "zh", wd, out, style, bgc, adv, log)
        log(f"中文版视频压制完成，时长 {dur_cn}s")

    # 3. 英文出海版视频压制
    if do_en:
        target_en = out if not do_cn else out_en
        dur_en, narr_en = render_single_video(script, "en", wd, target_en, style, bgc, adv, log)
        log(f"英文出海版视频压制完成，时长 {dur_en}s")

    return {
        "duration": dur_cn if do_cn else dur_en,
        "duration_en": dur_en,
        "has_cn": do_cn,
        "has_en": do_en,
        "script_source": src,
        "image_sources": srcs,
        "narration": narr_cn,
        "narration_en": narr_en,
        "script": script
    }
