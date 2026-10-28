"""视频生成流水线：脚本 -> 图片 -> 配音 -> ffmpeg 合成。提供者可插拔（环境变量配置）。"""
import os, json, math, random, subprocess, base64, re, hashlib, time, threading
import requests
from PIL import Image, ImageDraw, ImageFilter

FONT = os.getenv("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")
VOICE = os.getenv("TTS_VOICE", "Cherry")
BASE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE, "assets", "audio")
W, H = 1280, 720   # 插画/占位图的基础横屏尺寸
_CV = threading.local()
def dims():
    """当前任务的输出画布尺寸（线程隔离）：16:9 → 1280x720，9:16 → 1080x1920。"""
    return getattr(_CV, "wh", (1280, 720))
def set_canvas(aspect):
    _CV.wh = (1080, 1920) if aspect == "9:16" else (1280, 720)
def is_vertical(): return dims()[1] > dims()[0]
def comp_hint(): return "vertical 9:16 portrait composition" if is_vertical() else "16:9 composition"

# 可选配音音色（edge-tts，免费无需 Key）
VOICES = {
    "zh": [("zh-CN-XiaoxiaoNeural", "晓晓 · 温柔女声"), ("zh-CN-YunxiNeural", "云希 · 阳光男声"),
           ("zh-CN-YunjianNeural", "云健 · 浑厚男声"), ("zh-CN-XiaoyiNeural", "晓伊 · 活泼童趣女声"),
           ("zh-CN-YunxiaNeural", "云夏 · 童声男孩")],
    "en": [("en-US-JennyNeural", "Jenny · female"), ("en-US-GuyNeural", "Guy · male"),
           ("en-US-AriaNeural", "Aria · female"), ("en-US-AnaNeural", "Ana · child")],
}
VOICE_IDS = {v for l in VOICES.values() for v, _ in l}
STYLES = {
    "ink": "traditional Chinese ink-wash painting, muted monochrome with light red accents, rice paper texture, misty mountains",
    "kids": "warm colorful children's picture book illustration, soft watercolor, cute rounded characters",
}

# ---------------- 脚本 ----------------
# ---------------- 脚本 ----------------
BUILTIN = {
    "刻舟求剑": {
        "title": "刻舟求剑", "subtitle": "成语故事", "image_dir": "builtin/kezhouqiujian",
        "character": "an elderly man of the ancient Chu state, grey hair tied in a topknot, long white beard, wearing a loose light-grey hanfu robe",
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

TEMPLATE_CHARACTER = {
    "chengyu": "an ancient Chinese man in a plain grey hanfu robe, hair in a topknot, thin black beard, calm expression",
    "kepu": "a cheerful cartoon child with short black hair, round face, rosy cheeks, yellow T-shirt and blue shorts",
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
        "character": TEMPLATE_CHARACTER["chengyu" if kind != "kepu" else "kepu"],
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
              "4. 必须同时定制专属的【国内全平台通用中文发布物料（适配抖音/视频号/快手/小红书）】与【TikTok英文发布物料】：\n"
              "   - publish_info（中文）：爆款吸睛标题（<=30字，适合视频号、快手、抖音封面与文案）、通俗看点描述（50-80字）、5个国内短视频热门话题标签；\n"
              "   - publish_info_en（英文）：Viral TikTok Title (<=60字符)、Engaging Description (40-60 words)、5个热门英文标签（如 #LearnOnTikTok #ScienceFacts 等）。\n"
              '只输出JSON：{"title":"","subtitle":"","title_en":"","subtitle_en":"","publish_info":{"title":"","description":"","tags":["#标签1","#标签2"]},"publish_info_en":{"title":"","description":"","tags":["#Tag1","#Tag2"]},"scenes":[{"narration":"","narration_en":"","image_prompt":""}]}')
    prompt += ('\n另外在 JSON 顶层增加 "character" 字段：用一句英文写出贯穿全片的主角设定卡'
               '（外貌、年龄、发型、服饰颜色等固定特征），保证每个分镜的主角形象一致。')
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

def find_existing_job(topic, base_dir=None):
    """查找本地已有该主题的高清插画与剧本，供英文版无损继承，确保中英文版本插画绝对一致。"""
    if base_dir is None:
        base_dir = os.path.join(BASE, "output")
    if not os.path.exists(base_dir):
        return None
    clean_fn = lambda s: re.sub(r"[，。？?!！\s、：“”‘’（）《》…—,.!?~～]+", "", s)
    t_clean = clean_fn(topic)
    candidates = []
    for d in os.listdir(base_dir):
        p = os.path.join(base_dir, d)
        if not os.path.isdir(p):
            continue
        sf = os.path.join(p, "script.json")
        if not os.path.exists(sf):
            continue
        try:
            with open(sf, "r", encoding="utf-8") as f:
                s = json.load(f)
            if clean_fn(s.get("title", "")) == t_clean:
                n = len(s.get("scenes", []))
                if n >= 4 and all(os.path.exists(os.path.join(p, f"img{i}.png")) for i in range(n)):
                    candidates.append((os.path.getmtime(sf), p, s))
        except Exception:
            continue
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], candidates[0][2]
    return None

def translate_script_to_english(script, topic, kind):
    """当继承历史中文剧本时，若缺少英文旁白，调用大模型对齐翻译出英文旁白、标题与TikTok发布物料，100%保持原分镜结构。"""
    scenes = script.get("scenes", [])
    if all(sc.get("narration_en") for sc in scenes) and script.get("title_en"):
        return script

    base, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "qwen-plus")
    if not (base and key):
        for i, sc in enumerate(scenes):
            if not sc.get("narration_en"):
                sc["narration_en"] = f"Scene {i+1} of {topic}: {sc.get('narration')}"
        script["title_en"] = script.get("title_en") or topic
        script["subtitle_en"] = script.get("subtitle_en") or "Classic Story"
        return script

    system_prompt = (
        "You are an expert bilingual video translator and TikTok content creator. "
        "Given a Chinese video script with scene narrations, translate them into engaging, natural English narrations "
        "(15-25 words per scene) suitable for voiceover. Also create a viral TikTok title, description, and hashtags.\n"
        "Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "title_en": "English Video Title",\n'
        '  "subtitle_en": "English Subtitle",\n'
        '  "publish_info_en": {"title": "TikTok Title", "description": "Engaging caption", "tags": ["#Tag1", "#Tag2"]},\n'
        '  "scenes": [{"narration_en": "English narration for scene 1"}, ...]\n'
        "}"
    )
    user_payload = {
        "title": script.get("title", topic),
        "subtitle": script.get("subtitle", ""),
        "scenes": [sc.get("narration", "") for sc in scenes]
    }
    try:
        r = requests.post(base.rstrip("/") + "/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": [
                              {"role": "system", "content": system_prompt},
                              {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
                          ], "response_format": {"type": "json_object"}})
        if r.ok:
            data = json.loads(r.json()["choices"][0]["message"]["content"])
            script["title_en"] = data.get("title_en") or script.get("title_en") or topic
            script["subtitle_en"] = data.get("subtitle_en") or script.get("subtitle_en") or "Ancient Wisdom"
            if data.get("publish_info_en"):
                script["publish_info_en"] = data["publish_info_en"]
            trans_scenes = data.get("scenes", [])
            for i, sc in enumerate(scenes):
                if i < len(trans_scenes) and trans_scenes[i].get("narration_en"):
                    sc["narration_en"] = trans_scenes[i]["narration_en"]
    except Exception:
        pass
    return script

def get_script(topic, kind, log):
    s, src = _get_script(topic, kind, log)
    s = json.loads(json.dumps(s, ensure_ascii=False))   # 深拷贝，避免修改内置脚本
    s.setdefault("character", TEMPLATE_CHARACTER["kepu" if kind == "kepu" else "chengyu"])
    return s, src

def _get_script(topic, kind, log):
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
                {"role": "user", "content": [{"text": f"{prompt}. Style: {STYLES[style]}. {comp_hint()}, no text, no letters."}]}
            ]
        },
        "parameters": {
            "size": ("720*1280" if is_vertical() else os.getenv("IMAGE_SIZE", "1280*720")),
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

def api_image(prompt, style, out, ref=None):
    """OpenAI 兼容生图接口：/images/generations；传入参考图（主角首图）时改用 /images/edits 保持角色一致。"""
    key = os.getenv("IMAGE_API_KEY")
    base = os.getenv("IMAGE_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("IMAGE_MODEL", "gpt-image-1")
    size = "1024x1536" if is_vertical() else os.getenv("IMAGE_SIZE", "1536x1024")
    full = f"{prompt}. Style: {STYLES[style]}. {comp_hint()}, no text, no letters."
    if ref and os.path.exists(ref) and os.getenv("IMAGE_USE_REFERENCE", "1") == "1":
        with open(ref, "rb") as f:
            r = requests.post(base.rstrip("/") + "/images/edits", timeout=300, headers={"Authorization": f"Bearer {key}"},
                              files={"image": ("ref.png", f, "image/png")},
                              data={"model": model, "size": size, "n": 1,
                                    "prompt": full + " Keep the main character's face, hair and clothing identical to the reference image; new scene and pose."})
        if r.ok:
            d = r.json()["data"][0]
            raw = base64.b64decode(d["b64_json"]) if d.get("b64_json") else requests.get(d["url"], timeout=120).content
            return save_image(raw, out)
    r = requests.post(base.rstrip("/") + "/images/generations", timeout=300,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "prompt": full, "size": size, "n": 1})
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
                            "input": {"prompt": f"{prompt}. Style: {STYLES[style]}. {comp_hint()}, no text, no letters.",
                                      "negative_prompt": "文字, 字母, 水印, 低质量, 肢体畸形"},
                            "parameters": {"size": ("810*1440" if is_vertical() else os.getenv("IMAGE_SIZE", "1440*810")), "n": 1}})
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

def fit(path, out=None):
    """适配到当前画布：宽高比接近时居中裁剪；横图放进竖屏（或反之）时用模糊放大背景 + 完整原图居中，避免裁掉主体。"""
    W, H = dims(); im = Image.open(path).convert("RGB")
    def cover(img, w, h):
        s = max(w / img.width, h / img.height)
        img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)))
        l, t = (img.width - w) // 2, (img.height - h) // 2
        return img.crop((l, t, l + w, t + h))
    ra, rb = im.width / im.height, W / H
    if max(ra, rb) / min(ra, rb) < 1.3:
        res = cover(im, W, H)
    else:
        res = cover(im, W, H).filter(ImageFilter.GaussianBlur(40))
        res = Image.blend(res, Image.new("RGB", (W, H), (236, 228, 210)), 0.25)
        s = min(W / im.width, H / im.height); fg = im.resize((int(im.width * s), int(im.height * s)))
        y = (H - fg.height) // 2 - (int(H * 0.06) if H > W else 0)
        res.paste(fg, ((W - fg.width) // 2, y))
    res.save(out or path)

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

def get_image(script, i, style, out, log, ref=None):
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
            "openai": lambda p: api_image(p, style, out, ref=ref),
        }
        gen_fn = dispatch.get(provider, lambda p: qwen_image(p, style, out))

        char = (script.get("character") or "").strip()
        def with_char(pr):
            return f"{pr}. Main character (must look identical in every scene): {char}" if char else pr
        curr_prompt = with_char(sc["image_prompt"])
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
                    curr_prompt = with_char(sanitize_prompt_via_llm(sc["image_prompt"], topic, style))
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
    # 占位图：同一故事共用色板/人物剪影，seed 仅随场景与“重绘次数”变化
    seed = int(hashlib.md5((script["title"] + str(i) + str(sc.get("variant", 0))).encode()).hexdigest()[:8], 16)
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

def tts(text, out, lang="zh", voice=None, rate=None):
    """旁白配音：用户指定 edge-tts 音色/语速时直接使用 edge-tts；否则优先通义 qwen3-tts-flash，回退至 edge-tts。"""
    tts_provider = os.getenv("TTS_PROVIDER", "qwen")
    default_edge_voice = "en-US-JennyNeural" if lang == "en" else os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    edge_voice = voice if voice in VOICE_IDS else default_edge_voice
    rate_s = f"{int(rate):+d}%" if rate is not None else "-5%"
    use_qwen = tts_provider == "qwen" and not voice and rate is None
    attempts = [
        lambda: qwen_tts(text, out, lang=lang) if use_qwen else False,
        lambda: (run(["python3", "-m", "edge_tts", "--voice", edge_voice, f"--rate={rate_s}", "--text", text, "--write-media", out]) is None or True),
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

def _wrap_for_canvas(text, lang):
    """竖屏字幕更窄：中文每行约 13 字，英文约 28 字符。"""
    if not is_vertical(): return wrap_narration(text, lang=lang)
    if lang == "en":
        import textwrap
        return "\n".join(textwrap.wrap(text, width=28)[:4])
    if len(text) <= 13: return text
    k = math.ceil(len(text) / math.ceil(len(text) / 13))
    lines = [text[i:i + k] for i in range(0, len(text), k)]
    for j in range(1, len(lines)):   # 避免行首标点
        while lines[j] and lines[j][0] in "，。！？、；：,.!?;:”）》":
            lines[j - 1] += lines[j][0]; lines[j] = lines[j][1:]
    return "\n".join(l for l in lines if l)

def _tts_cached(text, wd, lang, opts):
    """按 文本+音色+语速 缓存配音，单镜重绘/重渲染时无需重复合成。"""
    voice = opts.get("voice_en" if lang == "en" else "voice_zh") or None
    rate = opts.get("rate")
    key = hashlib.md5(f"{lang}|{voice}|{rate}|{text}".encode()).hexdigest()[:12]
    f = os.path.join(wd, f"tts_{key}.mp3")
    if os.path.exists(f) and os.path.getsize(f) > 500: return f, True
    ok = tts(text, f, lang=lang, voice=voice, rate=rate)
    return f, ok

def pick_music(style, topic, choice):
    """背景音乐选择：auto=按画风（水墨→古风，绘本→轻快），none=不加。"""
    if choice == "none": return None
    kind = choice if choice in ("guofeng", "light") else ("light" if style == "kids" else "guofeng")
    n = int(hashlib.md5(topic.encode()).hexdigest(), 16) % 2 + 1
    f = os.path.join(AUDIO_DIR, f"music_{kind}_{n}.m4a")
    return f if os.path.exists(f) else None

def mix_audio(video, starts, total, style, topic, opts, wd):
    """背景音乐（随旁白自动闪避 ducking）+ 转场音效，视频流直接复制。"""
    music = pick_music(style, topic, opts.get("music", "auto"))
    sfx = opts.get("sfx", True)
    whoosh, chime = os.path.join(AUDIO_DIR, "sfx_whoosh.m4a"), os.path.join(AUDIO_DIR, "sfx_chime.m4a")
    if not music and not sfx: return
    ins = ["-i", video]; fc = ["[0:a]asplit=2[nar][sc]"]; mix = ["[nar]"]; k = 1
    if music:
        vol = float(os.getenv("MUSIC_VOLUME", "0.18"))
        ins += ["-stream_loop", "-1", "-i", music]
        fc.append(f"[{k}:a]volume={vol},atrim=0:{total:.2f},afade=t=in:d=1.5,afade=t=out:st={max(0, total - 2.5):.2f}:d=2.5[m]")
        fc.append("[m][sc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=400:makeup=1[md]")
        mix.append("[md]"); k += 1
    else:
        fc.append("[sc]anullsink")
    if sfx and os.path.exists(whoosh):
        ins += ["-i", chime, "-i", whoosh]
        fc.append(f"[{k}:a]volume=0.5,adelay=200|200[ch]"); mix.append("[ch]")
        cuts = starts[1:]
        if cuts:
            fc.append(f"[{k+1}:a]asplit={len(cuts)}" + "".join(f"[w{j}]" for j in range(len(cuts))))
            for j, t in enumerate(cuts):
                ms = max(0, int(t * 1000) - 250)
                fc.append(f"[w{j}]volume=0.45,adelay={ms}|{ms}[wd{j}]"); mix.append(f"[wd{j}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")
    tmp = video + ".mix.mp4"
    run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", "-t", f"{total:.2f}", tmp])
    os.replace(tmp, video)

def render_single_video(script, lang, wd, out_video, style, bgc, adv_fn, log, opts=None):
    """根据指定语言渲染独立视频版本（纯中文版或纯英文出海版），插画复用已有图片；支持 16:9 / 9:16。"""
    opts = opts or {}
    W, H = dims(); vert = is_vertical()
    is_en = (lang == "en")
    lang_tag = ("en" if is_en else "zh") + ("_v" if vert else "")
    prefix = "【英文出海版】" if is_en else "【中文版】"
    log(f"开始压制{prefix}{'竖屏 9:16 ' if vert else ''}成片...")

    # 1. 标题卡
    if is_en:
        t_val = script.get("title_en") or script.get("title", "")
        s_val = script.get("subtitle_en") or script.get("subtitle", "")
        fmt_t, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y = layout_title_en(t_val, s_val)
    else:
        t_val = script.get("title", "")
        s_val = script.get("subtitle", "")
        fmt_t, t_size, t_space, t_y, fmt_sub, s_size, s_space, s_y = layout_title_and_subtitle(t_val, s_val)
    if vert:   # 竖屏：标题字号随宽度缩放、纵向居中略偏上
        sc_ = W / 1280 * 1.1; t_size, s_size = int(t_size * sc_), int(s_size * sc_ * 1.2)
        t_y = f"(h-th)/2-{int(H*0.06)}"; s_y = f"h/2+{int(H*0.05)}"

    title_file = f"{wd}/title_{lang_tag}.txt"; subt_file = f"{wd}/subt_{lang_tag}.txt"
    open(title_file, "w", encoding="utf-8").write(fmt_t)
    open(subt_file, "w", encoding="utf-8").write(fmt_sub)
    t_audio, has_t = _tts_cached(t_val, wd, lang, opts)
    ain = ["-i", t_audio] if has_t else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:d=4", *ain, "-vf",
         f"drawtext=fontfile={FONT}:textfile={title_file}:fontsize={t_size}:fontcolor=0x28282d:line_spacing={t_space}:expansion=none:x=(w-tw)/2:y={t_y},"
         f"drawtext=fontfile={FONT}:textfile={subt_file}:fontsize={s_size}:fontcolor=0xaf281e:line_spacing={s_space}:expansion=none:x=(w-tw)/2:y={s_y}",
         "-af", "apad", "-t", "4", *enc(), f"{wd}/s_t_{lang_tag}.mp4"])
    segs = [f"{wd}/s_t_{lang_tag}.mp4"]; starts = [0.0]; t_acc = 4.0
    narr_ok = has_t

    # 2. 分镜
    sub_fontsize = (44 if is_en else 54) if vert else (30 if is_en else 36)
    sub_y = f"h*0.74" if vert else "h-th-40"
    for i, sc in enumerate(script["scenes"]):
        narration_text = (sc.get("narration_en") if is_en else sc.get("narration")) or sc.get("narration", "")
        a_file, ok = _tts_cached(narration_text, wd, lang, opts)
        narr_ok = narr_ok and ok
        d = (dur(a_file) if ok else max(4, len(narration_text.split() if is_en else narration_text) * (0.35 if is_en else 0.25))) + 1.2
        nf = int(d * 30)
        frame = f"{wd}/frame{i}_{lang_tag}.png"; fit(f"{wd}/img{i}.png", frame)
        sub_file = f"{wd}/sub{i}_{lang_tag}.txt"
        open(sub_file, "w", encoding="utf-8").write(_wrap_for_canvas(narration_text, lang))
        ai = ["-i", a_file] if ok else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        run(["ffmpeg", "-y", "-loop", "1", "-i", frame, *ai, "-filter_complex",
             f"[0]scale={W*2}:{H*2},zoompan=z='1+0.12*on/{nf}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={nf}:s={W}x{H}:fps=30,"
             f"drawtext=fontfile={FONT}:textfile={sub_file}:fontsize={sub_fontsize}:fontcolor=white:borderw={4 if vert else 3}:bordercolor=0x202020:line_spacing={14 if vert else 10}:expansion=none:x=(w-tw)/2:y={sub_y}[v];[1]apad[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.2f}", *enc(), f"{wd}/s{i}_{lang_tag}.mp4"])
        segs.append(f"{wd}/s{i}_{lang_tag}.mp4"); starts.append(t_acc); t_acc += d
        adv_fn(f"{prefix}第{i+1}段配音与画面完成")

    # 3. 拼接 + 混音
    list_file = f"{wd}/list_{lang_tag}.txt"
    open(list_file, "w", encoding="utf-8").write("".join(f"file '{os.path.abspath(s)}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-movflags", "+faststart", out_video])
    try:
        mix_audio(out_video, starts, dur(out_video), style, script.get("title", ""), opts, wd)
    except Exception as e:
        log(f"背景音乐/音效混音失败，保留纯旁白：{e}")
    return round(dur(out_video), 1), narr_ok

def make_script(topic, kind, log, lang_mode="both"):
    """仅生成（或继承）剧本，用于“先审稿再出图”流程。"""
    script, src = get_script(topic, kind, log)
    if lang_mode in ("both", "en"):
        script = translate_script_to_english(script, topic, kind)
    return script, src

def build(topic, kind, style, wd, out, progress, lang_mode="both", opts=None, script=None, regen=None):
    """流水线主函数：剧本 → 插画 → 配音 → 合成（中文版 / 英文出海版 / 双版本；16:9 或 9:16）。
    script: 用户审核/编辑后的剧本（提供时不再自动生成或继承）；regen: 需要重绘插画的场景下标列表。"""
    opts = opts or {}
    set_canvas(opts.get("aspect", "16:9"))
    os.makedirs(wd, exist_ok=True); log = lambda m: progress(None, m)
    import shutil

    if script is not None:
        src = script.get("_source", "edited")
    else:
        inherited_job = find_existing_job(topic)
        if inherited_job and (lang_mode == "en" or not os.path.exists(f"{wd}/img0.png")):
            exist_p, exist_s = inherited_job
            log(f"检测到《{topic}》已有高清插画，已自动继承！确保中英文版本画面 100% 镜头一致")
            script = translate_script_to_english(exist_s, topic, kind)
            src = "inherited"
            for i in range(len(script.get("scenes", []))):
                src_img = os.path.join(exist_p, f"img{i}.png"); dst_img = f"{wd}/img{i}.png"
                if os.path.exists(src_img) and not os.path.exists(dst_img):
                    shutil.copy2(src_img, dst_img)
        else:
            script, src = get_script(topic, kind, log)
    script.setdefault("character", TEMPLATE_CHARACTER["kepu" if kind == "kepu" else "chengyu"])
    if lang_mode in ("both", "en") and not all(sc.get("narration_en") for sc in script["scenes"]):
        script = translate_script_to_english(script, topic, kind)

    for i in (regen or []):   # 单镜重绘：删除旧图并递增 variant
        if 0 <= i < len(script["scenes"]):
            sc = script["scenes"][i]; sc["variant"] = int(sc.get("variant", 0)) + 1
            for f in (f"{wd}/img{i}.png", f"{wd}/img{i}.png.src"):
                if os.path.exists(f): os.remove(f)

    json.dump(script, open(f"{wd}/script.json", "w"), ensure_ascii=False, indent=1)
    n = len(script["scenes"])
    do_cn = lang_mode in ("both", "cn"); do_en = lang_mode in ("both", "en")
    total_steps = 2 + n + n * ((1 if do_cn else 0) + (1 if do_en else 0))
    step = [1]
    def adv(m):
        step[0] += 1; progress(int(100 * step[0] / total_steps), m)
    progress(int(100 / total_steps), f"剧本就绪（{src}），共{n}个场景")

    srcs = []
    for i in range(n):
        img_target = f"{wd}/img{i}.png"
        if os.path.exists(img_target) and os.path.getsize(img_target) > 1000:
            srcs.append("reused"); adv(f"第{i+1}张插画复用")
        else:
            ref = f"{wd}/img0.png.src" if i > 0 else None   # 以首图为角色参考图（支持的提供方）
            if script.get("image_dir") and i in (regen or []):
                sv = script["image_dir"]; script["image_dir"] = None
                srcs.append(get_image(script, i, style, img_target, log, ref=ref)); script["image_dir"] = sv
            else:
                srcs.append(get_image(script, i, style, img_target, log, ref=ref))
            adv(f"第{i+1}张插画生成完成（{srcs[-1]}）")

    bgc = "0xFAF0D7" if style == "kids" else "0xECE4D2"
    dur_cn = dur_en = 0; narr_cn = narr_en = False
    out_en = os.path.splitext(out)[0] + "_en.mp4"
    if do_cn:
        dur_cn, narr_cn = render_single_video(script, "zh", wd, out, style, bgc, adv, log, opts)
        log(f"中文版视频压制完成，时长 {dur_cn}s")
    if do_en:
        target_en = out if not do_cn else out_en
        dur_en, narr_en = render_single_video(script, "en", wd, target_en, style, bgc, adv, log, opts)
        log(f"英文出海版视频压制完成，时长 {dur_en}s")
    json.dump(script, open(f"{wd}/script.json", "w"), ensure_ascii=False, indent=1)
    return {"duration": dur_cn if do_cn else dur_en, "duration_en": dur_en, "has_cn": do_cn, "has_en": do_en,
            "script_source": src, "image_sources": srcs, "narration": narr_cn, "narration_en": narr_en,
            "aspect": opts.get("aspect", "16:9"), "script": script}
