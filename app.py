import os, math, uuid, queue, threading, time, json, sqlite3, secrets, traceback, datetime, re, subprocess
from collections import defaultdict, deque
from zoneinfo import ZoneInfo
import bcrypt
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pipeline, payments

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.getenv("OUTPUT_DIR", os.path.join(BASE, "output")); os.makedirs(OUT, exist_ok=True)
DB = os.getenv("DB_PATH", os.path.join(BASE, "app.db"))
DAILY_QUOTA = int(os.getenv("DAILY_QUOTA", "3"))
TZ = ZoneInfo(os.getenv("QUOTA_TZ", "Asia/Shanghai"))
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
LOGIN_MAX, LOGIN_WINDOW = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10")), int(os.getenv("LOGIN_WINDOW_SEC", "900"))
COOKIE = "session"

app = FastAPI(title="成语/科普 短视频生成器")
Q = queue.Queue(); LOCK = threading.Lock()

def db():
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False); c.row_factory = sqlite3.Row; return c

def init_db():
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
          is_admin INTEGER DEFAULT 0, quota INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id INTEGER, topic TEXT, kind TEXT, style TEXT, status TEXT,
          progress INTEGER, message TEXT, log TEXT DEFAULT '[]', result TEXT, created REAL, day TEXT);
        CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id, day);""")
        au, ap = os.getenv("ADMIN_USERNAME"), os.getenv("ADMIN_PASSWORD")
        if au and ap:
            h = hashpw(ap); r = c.execute("SELECT id FROM users WHERE username=?", (au,)).fetchone()
            if r: c.execute("UPDATE users SET pw_hash=?, is_admin=1 WHERE id=?", (h, r["id"]))
            else: c.execute("INSERT INTO users(username,pw_hash,is_admin,created) VALUES(?,?,1,?)", (au, h, time.time()))
        # 重启恢复：中断的任务重新排队
        c.execute("UPDATE jobs SET status='queued', progress=0, message='服务重启，重新排队' WHERE status='running'")
        # 兼容旧表升级：检查并自动添加 lang 字段
        cols = [col[1] for col in c.execute("PRAGMA table_info(jobs)").fetchall()]
        if "lang" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN lang TEXT DEFAULT 'both'")
        for col, ddl in [("opts", "TEXT DEFAULT '{}'"), ("phase", "TEXT DEFAULT 'full'"), ("regen", "TEXT DEFAULT '[]'")]:
            if col not in cols: c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
        ucols = [col[1] for col in c.execute("PRAGMA table_info(users)").fetchall()]
        for col, ddl in [("plan", "TEXT"), ("plan_expires", "REAL")]:
            if col not in ucols: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT, plan_name TEXT, amount_cents INTEGER,
          days INTEGER, provider TEXT, status TEXT, created REAL, paid_at REAL, trade_no TEXT, note TEXT);
        CREATE TABLE IF NOT EXISTS regens(id INTEGER PRIMARY KEY, user_id INTEGER, job_id TEXT, scene INTEGER, day TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS regens_user ON regens(user_id, day);""")
        return [r["id"] for r in c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created")]

def hashpw(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt(12)).decode()
def today(): return datetime.datetime.now(TZ).strftime("%Y-%m-%d")

# 经典与高频主题精品物料知识库
DOUYIN_KNOWLEDGE_LIBRARY = {
    "洗澡": {
        "title": "洗澡久了手指头为什么会起皱？原来暗藏进化超能力！",
        "description": "洗澡或游泳久了手指就皱巴巴？这可不是皮肤吸水变胖，而是自主神经系统的主动进化防御！起皱的指纹就像汽车轮胎花纹，能在水下牢牢抓住湿滑物体。关注我，每天看懂身边的硬核科学！",
        "tags": ["#洗澡手指起皱", "#人体冷知识", "#生物进化", "#十万个为什么", "#原来如此"]
    },
    "天空": {
        "title": "为什么天空是蓝色的？阳光中蓝光被大气散射的秘密！",
        "description": "看似白色的阳光其实藏着七彩色光！进入大气层后，短波长的蓝光更容易被空气分子散射到四面八方，照亮整片天空。关注我，每天看懂身边的硬核科学！",
        "tags": ["#为什么天空是蓝色的", "#光学散射", "#大自然的奥秘", "#少儿科普", "#原来如此"]
    },
    "含羞草": {
        "title": "含羞草轻轻碰一下叶子为什么会合拢？看完彻底懂了！",
        "description": "轻轻一碰就羞答答闭上，植物没有肌肉凭什么会动？叶枕双水球膨压、生物电信号闪电传递、钾离子外流抽水与暴雨防御装甲！关注我，每天看懂身边的硬核科学！",
        "tags": ["#含羞草为什么会合拢", "#植物微观世界", "#细胞膨压", "#生物物理", "#原来如此"]
    },
    "可乐": {
        "title": "喝冰可乐为什么会打嗝？原来肚子里在沸腾！",
        "description": "一口冰可乐喝下去，“嗝~”一声太痛快了！为什么可乐里的气泡一进肚子就疯狂造反？原来37度的胃正在上演一场气体大逃亡！关注我，每天看懂身边的硬核科学！",
        "tags": ["#为什么喝可乐会打嗝", "#碳酸饮料", "#人体科学", "#大自然的奥秘", "#原来如此"]
    },
    "彩虹": {
        "title": "雨过天晴彩虹是怎么形成的？看光的折射与色散奥秘！",
        "description": "雨过天晴，天空为什么会架起一道七彩拱桥？看似透明的阳光里，竟然藏着红橙黄绿青蓝紫七个小精灵！带孩子看懂光的折射与色散奥秘。关注我，每天解锁身边的科学秘密！",
        "tags": ["#彩虹是怎么形成的", "#大自然的奥秘", "#科学启蒙", "#物理光学", "#原来如此"]
    },
    "做梦": {
        "title": "为什么晚上会做奇怪又好玩的梦？原来大脑在拼积木！",
        "description": "小恐龙怎么穿上了芭蕾裙？小猫咪怎么长出了蝴蝶翅膀？别怕，这是夜里大脑小精灵在给记忆分门别类呢！关注我，每天一个睡前科学小故事，陪宝宝聪明入睡！",
        "tags": ["#为什么会做梦", "#大脑的秘密", "#幼儿童科学", "#幼儿睡前故事", "#原来如此"]
    },
    "刻舟求剑": {
        "title": "刻舟求剑在物理学上到底错在哪个运动参照系？",
        "description": "古人乘船渡江剑落水中，在船舷刻记号真能找到剑吗？用现代物理经典力学的运动参照系与流体力学深度拆解！关注我，每天看懂一个硬核成语典故。",
        "tags": ["#刻舟求剑", "#成语物理学", "#运动参照系", "#硬核国学", "#经典力学", "#原来如此"]
    },
    "守株待兔": {
        "title": "守株待兔：古代寓言背后概率学与心理学的冷知识！",
        "description": "撞树的野兔只是极低概率事件，农夫却放弃耕种苦等奇迹！从概率论与幸存者偏差拆解为何侥幸心理不可取。关注我，每天看懂一个硬核成语典故。",
        "tags": ["#守株待兔", "#概率论", "#幸存者偏差", "#成语故事", "#原来如此"]
    },
    "闻鸡起舞": {
        "title": "闻鸡起舞：祖逖与刘琨清晨挥剑报国的励志传奇！",
        "description": "西晋末年祖逖与刘琨闻鸡鸣即起习武磨砺，不仅是热血报国的典范，更是坚持自律刻意练习的顶级心力！关注我，每天看懂一个硬核成语典故。",
        "tags": ["#闻鸡起舞", "#成语故事", "#历史冷知识", "#自律励志", "#原来如此"]
    }
}

def get_douyin_publish_info(topic: str, kind: str = "chengyu", style: str = "ink", script: dict | None = None) -> dict:
    """根据科普/成语主题生成抖音平台专属发布物料（标题严格控制在30字内、作品描述与热门话题标签）。
    优先读取大模型生成专属物料，其次匹配主题知识库，最后基于分镜剧本内容智能动态提炼。
    """
    clean_topic = re.sub(r"[，。？?!！\s、：“”‘’（）《》…—,.!?~～]+", "", topic)
    
    # 1. 优先使用 script 中的专属物料
    if isinstance(script, dict) and script.get("publish_info"):
        pi = script["publish_info"]
        if isinstance(pi, dict) and pi.get("title") and pi.get("description"):
            t = pi["title"].strip()[:30]
            d = pi["description"].strip()
            tags = pi.get("tags") or [f"#{clean_topic[:6]}", "#原来如此"]
            tags_str = " ".join(tags)
            return {
                "title": t,
                "char_count": len(t),
                "description": d,
                "tags": tags,
                "full_desc": f"{d}\n{tags_str}",
                "all_in_one": f"{t}\n\n{d}\n{tags_str}"
            }

    # 2. 匹配专属知识库
    for k, v in DOUYIN_KNOWLEDGE_LIBRARY.items():
        if k in clean_topic:
            t = v["title"][:30]
            d = v["description"]
            tags = v["tags"]
            tags_str = " ".join(tags)
            return {
                "title": t,
                "char_count": len(t),
                "description": d,
                "tags": tags,
                "full_desc": f"{d}\n{tags_str}",
                "all_in_one": f"{t}\n\n{d}\n{tags_str}"
            }

    # 3. 基于剧本内容智能提炼专属描述与标题（杜绝千篇一律模板）
    first_narration = ""
    last_narration = ""
    if isinstance(script, dict) and script.get("scenes"):
        scenes = script["scenes"]
        if scenes:
            first_narration = scenes[0].get("narration", "")
            last_narration = scenes[-1].get("narration", "")

    if len(clean_topic) <= 20:
        if clean_topic.endswith(("？", "!", "！", "?")):
            gen_title = f"{clean_topic}看完彻底涨知识了！"
        else:
            gen_title = f"{clean_topic}？背后原来暗藏玄机！"
    else:
        gen_title = f"{clean_topic[:20]}…原来背后暗藏玄机！"
    if len(gen_title) > 30:
        gen_title = gen_title[:30]

    if last_narration:
        desc = f"{first_narration} {last_narration} 关注我，每天看懂身边的硬核科学与国学智慧！"
    elif style == "kids":
        desc = f"关于【{clean_topic}】，大自然里到底藏着怎样好玩的科学秘密？用生动动画为孩子讲懂身边奇妙世界。关注我，每天学点睡前小科学！"
    elif kind == "chengyu":
        desc = f"流传千年的中国成语【{clean_topic}】，背后到底暗藏着古人怎样的博弈智慧与物理规律？关注我，每天看懂一个硬核成语典故！"
    else:
        desc = f"生活中常见的【{clean_topic}】现象，底层到底遵循怎样的科学原理与物理定律？关注我，每天看懂身边的硬核科学！"

    tags = [f"#{clean_topic[:6]}" if clean_topic else "#科普", "#原来如此", "#涨知识", "#硬核科普", "#冷知识"]
    tags_str = " ".join(tags)
    full_desc = f"{desc}\n{tags_str}"

    return {
        "title": gen_title,
        "char_count": len(gen_title),
        "description": desc,
        "tags": tags,
        "full_desc": full_desc,
        "all_in_one": f"{gen_title}\n\n{full_desc}"
    }

def filter_uncreated_topics(data_dict: dict) -> dict:
    """过滤掉在当前数据库中已经生成过的选题，确保题库呈现的均为待创作的新鲜选题。
    使用 Lambda 表达式与容错比对。
    """
    clean_fn = lambda s: re.sub(r"[，。？?!！\s、：“”‘’（）《》…—,.!?~～]+", "", s)
    with db() as c:
        rows = c.execute("SELECT topic FROM jobs").fetchall()
    existing = [clean_fn(r["topic"]) for r in rows]

    filtered = {}
    for cat, topics in data_dict.items():
        survived = []
        for t in topics:
            tc = clean_fn(t)
            is_generated = any(
                tc == ep or (len(tc) >= 5 and tc in ep) or (len(ep) >= 5 and ep in tc)
                for ep in existing
            )
            if not is_generated:
                survived.append(t)
        filtered[cat] = survived
    return filtered

def job_dict(r):
    """将数据库任务记录转换为前端展示所需的标准字典对象，并自动附加抖音与 TikTok 双语发布物料与视频播放链接。"""
    d = dict(r)
    d["log"] = json.loads(d["log"] or "[]")
    res = json.loads(d.pop("result") or "{}")
    d.update(res)
    jid = d["id"]
    if d["status"] == "done":
        has_cn = d.get("has_cn", True)
        has_en = d.get("has_en", False)
        if has_cn or os.path.exists(os.path.join(OUT, f"{jid}.mp4")):
            d["video"] = f"/api/jobs/{jid}/video?lang=cn"
        if has_en or os.path.exists(os.path.join(OUT, f"{jid}_en.mp4")):
            d["video_en"] = f"/api/jobs/{jid}/video?lang=en"
            d["has_en"] = True
    script_obj = d.get("script")
    d["publish_info"] = get_douyin_publish_info(d["topic"], d.get("kind", "chengyu"), d.get("style", "ink"), script_obj)
    if script_obj and script_obj.get("publish_info_en"):
        d["publish_info_en"] = script_obj["publish_info_en"]
    else:
        d["publish_info_en"] = {
            "title": f"The Secret Behind {d['topic']} Revealed!",
            "description": f"Ever wondered about {d['topic']}? Here is the fascinating science and story behind it. Follow for more mind-blowing daily facts!",
            "tags": ["#ScienceFacts", "#DidYouKnow", "#LearnOnTikTok", "#ViralVideo", "#StoryTime"]
        }
    d.pop("user_id", None)
    return d

def update_job(jid, **kw):
    with LOCK, db() as c:
        c.execute(f"UPDATE jobs SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), jid))

def worker():
    while True:
        jid = Q.get()
        with db() as c: r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r or r["status"] != "queued": continue
        log = []; update_job(jid, status="running", message="开始生成")
        def prog(p, m):
            log.append(m); kw = dict(message=m, log=json.dumps(log, ensure_ascii=False))
            if p is not None: kw["progress"] = min(p, 99)
            update_job(jid, **kw)
        try:
            lang_mode = r["lang"] if "lang" in r.keys() and r["lang"] else "both"
            opts = json.loads(r["opts"] or "{}"); phase = r["phase"] or "full"
            prev = json.loads(r["result"] or "{}")
            wd = os.path.join(OUT, jid)
            if phase == "script":
                script, src = pipeline.make_script(r["topic"], r["kind"], prog, lang_mode)
                script["_source"] = src
                update_job(jid, status="review", progress=0, message="剧本已生成，请审核修改后确认生成画面",
                           result=json.dumps({"script": script, "script_source": src}, ensure_ascii=False))
                continue
            script = prev.get("script") if phase in ("render", "regen") else None
            regen = json.loads(r["regen"] or "[]") if phase == "regen" else None
            res = pipeline.build(r["topic"], r["kind"], r["style"], wd, os.path.join(OUT, f"{jid}.mp4"), prog,
                                 lang_mode=lang_mode, opts=opts, script=script, regen=regen)
            update_job(jid, status="done", progress=100, message="完成", phase="done", result=json.dumps(res, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            if (r["phase"] or "") == "regen":   # 重绘失败：保留原成片，不影响原任务计数
                update_job(jid, status="done", phase="done", message=f"单镜重绘失败（原视频保留）：{e}")
            else:
                update_job(jid, status="error", message=f"失败：{e}")

@app.on_event("startup")
def startup():
    for jid in init_db(): Q.put(jid)
    for _ in range(int(os.getenv("WORKERS", "1"))): threading.Thread(target=worker, daemon=True).start()

# ---------------- 认证 ----------------
FAILS = defaultdict(deque)
def client_ip(req: Request):
    if os.getenv("TRUST_PROXY") == "1" and req.headers.get("x-forwarded-for"):
        return req.headers["x-forwarded-for"].split(",")[0].strip()
    return req.client.host if req.client else "?"

def check_rate(ip):
    dq = FAILS[ip]; now = time.time()
    while dq and dq[0] < now - LOGIN_WINDOW: dq.popleft()
    if len(dq) >= LOGIN_MAX: raise HTTPException(429, f"尝试次数过多，请{int((dq[0]+LOGIN_WINDOW-now)/60)+1}分钟后再试")

def current_user(req: Request):
    t = req.cookies.get(COOKIE)
    if t:
        with db() as c:
            r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?", (t, time.time())).fetchone()
        if r: return dict(r)
    raise HTTPException(401, "请先登录")

def admin_user(u=Depends(current_user)):
    if not u["is_admin"]: raise HTTPException(403, "需要管理员权限")
    return u

def start_session(resp: Response, uid):
    t = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (t, uid, time.time() + SESSION_DAYS * 86400))
    resp.set_cookie(COOKIE, t, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")

class Cred(BaseModel):
    username: str
    password: str

@app.post("/api/register")
def register(c: Cred, req: Request, resp: Response):
    check_rate(client_ip(req))
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff]{3,20}", c.username): raise HTTPException(400, "用户名需3-20位，仅限字母、数字、下划线或汉字")
    if not 8 <= len(c.password) <= 72: raise HTTPException(400, "密码长度需为8-72位")
    try:
        with db() as d: uid = d.execute("INSERT INTO users(username,pw_hash,created) VALUES(?,?,?)", (c.username, hashpw(c.password), time.time())).lastrowid
    except sqlite3.IntegrityError:
        FAILS[client_ip(req)].append(time.time()); raise HTTPException(409, "用户名已被注册")
    start_session(resp, uid); return {"ok": True}

DUMMY = hashpw("dummy-password")
@app.post("/api/login")
def login(c: Cred, req: Request, resp: Response):
    ip = client_ip(req); check_rate(ip)
    with db() as d: r = d.execute("SELECT * FROM users WHERE username=?", (c.username,)).fetchone()
    ok = bcrypt.checkpw(c.password.encode()[:72], (r["pw_hash"] if r else DUMMY).encode())
    if not (r and ok):
        FAILS[ip].append(time.time()); raise HTTPException(401, "用户名或密码错误")
    FAILS.pop(ip, None); start_session(resp, r["id"]); return {"ok": True}

@app.post("/api/logout")
def logout(req: Request, resp: Response):
    t = req.cookies.get(COOKIE)
    if t:
        with db() as c: c.execute("DELETE FROM sessions WHERE token=?", (t,))
    resp.delete_cookie(COOKIE, path="/"); return {"ok": True}

# ---------------- 套餐与配额配置（DB 优先，其次 config/plans.json / PLANS_FILE，最后环境变量默认） ----------------
REGEN_PER_QUOTA = int(os.getenv("REGEN_PER_QUOTA", "3"))
def default_plans_config():
    f = os.getenv("PLANS_FILE", os.path.join(BASE, "config", "plans.json"))
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh: return json.load(fh)
        except Exception: traceback.print_exc()
    return {"free_daily_quota": DAILY_QUOTA,
            "plans": [{"id": "monthly", "name": "月卡", "price_cents": 1990, "days": 30, "daily_quota": 5, "desc": "30 天内每天 5 次生成"}]}

def plans_config():
    with db() as c: r = c.execute("SELECT value FROM settings WHERE key='plans'").fetchone()
    return json.loads(r["value"]) if r else default_plans_config()

def find_plan(pid):
    return next((p for p in plans_config()["plans"] if p["id"] == pid), None)

def active_plan(u):
    if u.get("plan") and (u.get("plan_expires") or 0) > time.time():
        p = find_plan(u["plan"])
        if p: return p
    return None

def quota_info(u):
    plan = active_plan(u)
    if u["is_admin"]: q = None
    elif u["quota"] is not None: q = u["quota"]                 # 管理员单独设置的配额优先
    elif plan: q = plan.get("daily_quota")                         # None = 不限
    else: q = int(plans_config().get("free_daily_quota", DAILY_QUOTA))
    with db() as c:
        jobs = c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND day=? AND status NOT IN ('error','cancelled')", (u["id"], today())).fetchone()[0]
        regens = c.execute("SELECT COUNT(*) FROM regens WHERE user_id=? AND day=?", (u["id"], today())).fetchone()[0]
    used = jobs + math.ceil(regens / REGEN_PER_QUOTA)
    return {"quota": q, "used": used, "jobs_today": jobs, "regens_today": regens, "regen_per_quota": REGEN_PER_QUOTA,
            "remaining": None if q is None else max(0, q - used),
            "plan": plan["id"] if plan else "free", "plan_name": plan["name"] if plan else "免费版",
            "plan_expires": u.get("plan_expires") if plan else None}

@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"username": u["username"], "is_admin": bool(u["is_admin"]), **quota_info(u)}

# ---------------- 任务 ----------------
class Req(BaseModel):
    topic: str
    kind: str = "chengyu"
    style: str = "ink"
    mode: str | None = None
    lang: str = "both"
    aspect: str = "16:9"          # 16:9 | 9:16
    music: str = "auto"           # auto | guofeng | light | none
    sfx: bool = True
    voice_zh: str | None = None   # edge-tts 音色，None = 默认
    voice_en: str | None = None
    rate: int | None = None       # 语速 -50..50 (%)
    review: bool = False          # True = 先生成剧本供审核

CREATE_LOCK = threading.Lock()
ACTIVE = ('queued', 'running', 'review')
def check_busy(c, u, exclude=None):
    if u["is_admin"]: return
    row = c.execute(f"SELECT id,status FROM jobs WHERE user_id=? AND status IN {ACTIVE} AND id!=?", (u["id"], exclude or "")).fetchone()
    if row:
        raise HTTPException(429, "你有一个剧本待审核，请先确认或取消" if row["status"] == "review" else "你已有一个视频正在生成，请等待完成后再提交")
@app.post("/api/jobs")
def create(r: Req, u=Depends(current_user)):
    t = r.topic.strip()
    if not t or len(t) > 40: raise HTTPException(400, "请输入1-40字的主题")
    if r.mode == "kids":
        r.kind = "kepu"; r.style = "kids"
    elif r.mode == "adult":
        r.kind = "kepu"; r.style = "ink"
    elif r.mode == "idiom":
        r.kind = "chengyu"; r.style = "ink"
    if r.kind not in ("chengyu", "kepu") or r.style not in ("ink", "kids"): raise HTTPException(400, "参数错误")
    lang_mode = r.lang if r.lang in ("both", "cn", "en") else "both"
    if r.aspect not in ("16:9", "9:16") or r.music not in ("auto", "guofeng", "light", "none"): raise HTTPException(400, "参数错误")
    for v in (r.voice_zh, r.voice_en):
        if v and v not in pipeline.VOICE_IDS: raise HTTPException(400, "不支持的音色")
    if r.rate is not None and not -50 <= r.rate <= 50: raise HTTPException(400, "语速需在 -50% ~ +50% 之间")
    opts = {"aspect": r.aspect, "music": r.music, "sfx": r.sfx, "voice_zh": r.voice_zh, "voice_en": r.voice_en, "rate": r.rate}
    with CREATE_LOCK:
        qi = quota_info(u)
        if qi["remaining"] is not None and qi["remaining"] <= 0:
            raise HTTPException(429, f"今日生成次数已用完（每日{qi['quota']}次），请明天再来")
        with db() as c:
            check_busy(c, u)
            jid = uuid.uuid4().hex[:12]
            c.execute("INSERT INTO jobs(id,user_id,topic,kind,style,lang,status,progress,message,created,day,opts,phase) VALUES(?,?,?,?,?,?,'queued',0,?,?,?,?,?)",
                      (jid, u["id"], t, r.kind, r.style, lang_mode, f"排队中（前面{Q.qsize()}个）", time.time(), today(),
                       json.dumps(opts), "script" if r.review else "full"))
    Q.put(jid); return get(jid, u)

def own_job(jid, u):
    with db() as c: r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r or (r["user_id"] != u["id"] and not u["is_admin"]): raise HTTPException(404, "任务不存在")
    return r

@app.get("/api/jobs")
def list_jobs(u=Depends(current_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 50", (u["id"],)).fetchall()
    return [{k: v for k, v in job_dict(r).items() if k not in ("log", "script")} for r in rows]

@app.get("/api/jobs/{jid}")
def get(jid: str, u=Depends(current_user)): return job_dict(own_job(jid, u))

@app.get("/api/jobs/{jid}/video")
def video(jid: str, lang: str = "cn", download: int = 0, u=Depends(current_user)):
    r = own_job(jid, u)
    filename_suffix = "_en" if lang == "en" else ""
    p = os.path.join(OUT, f"{jid}{filename_suffix}.mp4")
    if not os.path.exists(p):
        p = os.path.join(OUT, f"{jid}.mp4")
        if not os.path.exists(p): raise HTTPException(404, "视频不存在")
    display_name = f"{r['topic']}{'_英文出海版' if lang == 'en' else ''}.mp4"
    return FileResponse(p, media_type="video/mp4", filename=display_name if download else None)

@app.get("/api/config")
def config(u=Depends(current_user)):
    return {"llm": bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY")), "image": bool(os.getenv("IMAGE_API_KEY")),
            "voice": pipeline.VOICE, "builtin": list(pipeline.BUILTIN)}

class OpenFinderReq(BaseModel):
    id: str
    lang: str = "cn"

@app.post("/api/open_finder")
def open_finder(req: OpenFinderReq, u=Depends(current_user)):
    """在 macOS 访达中定位并高亮选中的成片视频文件（支持中文版与英文出海版）。"""
    job = own_job(req.id, u)
    target_name = f"{job['id']}_en.mp4" if req.lang == "en" else f"{job['id']}.mp4"
    p = os.path.join(OUT, target_name)
    target = p if os.path.exists(p) else os.path.join(OUT, f"{job['id']}.mp4")
    if not os.path.exists(target):
        target = os.path.join(OUT, job['id'])
    if not os.path.exists(target):
        raise HTTPException(404, "视频文件不存在")
    try:
        subprocess.run(["open", "-R", str(target)], check=True)
        return {"status": "success", "path": str(target)}
    except Exception as e:
        raise HTTPException(500, f"打开访达失败: {e}")

@app.get("/api/topics_kids_80")
def get_topics_kids_80():
    """获取过滤已创作选题后的 3-8 岁幼儿童趣题库。"""
    p = os.path.join(BASE, "data", "topics_kids_80.json")
    if not os.path.exists(p): return {}
    with open(p, "r", encoding="utf-8") as f: data = json.load(f)
    return filter_uncreated_topics(data)

@app.get("/api/topics_300")
def get_topics_300():
    """获取过滤已创作选题后的 10 岁+ 少年/成人硬核科普题库。"""
    p = os.path.join(BASE, "data", "topics_300.json")
    if not os.path.exists(p): return {}
    with open(p, "r", encoding="utf-8") as f: data = json.load(f)
    return filter_uncreated_topics(data)

@app.get("/api/topics_idiom_300")
def get_topics_idiom_300():
    """获取过滤已创作选题后的中国成语奇趣硬核溯源题库。"""
    p = os.path.join(BASE, "data", "topics_idiom_300.json")
    if not os.path.exists(p): return {}
    with open(p, "r", encoding="utf-8") as f: data = json.load(f)
    return filter_uncreated_topics(data)

# ---------------- 剧本审核 / 单镜重绘 ----------------
@app.get("/api/options")
def options(u=Depends(current_user)):
    return {"voices": pipeline.VOICES, "aspects": ["16:9", "9:16"],
            "music": [["auto", "按画风自动"], ["guofeng", "古风"], ["light", "轻快"], ["none", "无音乐"]],
            "regen_per_quota": REGEN_PER_QUOTA}

class SceneEdit(BaseModel):
    narration: str
    narration_en: str | None = None
    image_prompt: str | None = None

class ScriptEdit(BaseModel):
    title: str | None = None
    title_en: str | None = None
    character: str | None = None
    scenes: list[SceneEdit]

def _apply_scene(sc, e: SceneEdit):
    n = e.narration.strip()
    if not 1 <= len(n) <= 120: raise HTTPException(400, "每个场景中文旁白需为 1-120 字")
    sc["narration"] = n
    if e.narration_en is not None:
        if len(e.narration_en) > 400: raise HTTPException(400, "英文旁白过长")
        sc["narration_en"] = e.narration_en.strip()
    if e.image_prompt is not None:
        if len(e.image_prompt) > 600: raise HTTPException(400, "画面描述过长")
        sc["image_prompt"] = e.image_prompt.strip()

@app.get("/api/jobs/{jid}/script")
def get_script(jid: str, u=Depends(current_user)):
    r = own_job(jid, u); return json.loads(r["result"] or "{}").get("script") or {}

@app.put("/api/jobs/{jid}/script")
def put_script(jid: str, e: ScriptEdit, u=Depends(current_user)):
    r = own_job(jid, u)
    if r["status"] != "review": raise HTTPException(409, "当前状态不可编辑剧本")
    res = json.loads(r["result"] or "{}"); s = res["script"]
    if len(e.scenes) != len(s["scenes"]): raise HTTPException(400, "场景数量不可改变")
    for sc, ed in zip(s["scenes"], e.scenes): _apply_scene(sc, ed)
    if e.title is not None:
        if not 1 <= len(e.title.strip()) <= 40: raise HTTPException(400, "标题需为 1-40 字")
        s["title"] = e.title.strip()
    if e.title_en is not None: s["title_en"] = e.title_en.strip()[:120]
    if e.character is not None: s["character"] = e.character.strip()[:400]
    s["_source"] = "edited"
    update_job(jid, result=json.dumps(res, ensure_ascii=False)); return s

@app.post("/api/jobs/{jid}/confirm")
def confirm(jid: str, u=Depends(current_user)):
    r = own_job(jid, u)
    if r["status"] != "review": raise HTTPException(409, "当前状态不可确认")
    update_job(jid, status="queued", phase="render", progress=0, message="剧本已确认，排队生成画面")
    Q.put(jid); return get(jid, u)

@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str, u=Depends(current_user)):
    r = own_job(jid, u)
    if r["status"] != "review": raise HTTPException(409, "只能取消待审核的剧本")
    update_job(jid, status="cancelled", message="已取消（不计入配额）"); return {"ok": True}

class RegenReq(BaseModel):
    narration: str | None = None
    narration_en: str | None = None
    image_prompt: str | None = None

@app.get("/api/jobs/{jid}/scenes/{idx}/image")
def scene_image(jid: str, idx: int, u=Depends(current_user)):
    own_job(jid, u); p = os.path.join(OUT, jid, f"img{idx}.png")
    if not os.path.exists(p): raise HTTPException(404)
    return FileResponse(p, media_type="image/png")

@app.post("/api/jobs/{jid}/scenes/{idx}/regenerate")
def regenerate_scene(jid: str, idx: int, body: RegenReq, u=Depends(current_user)):
    r = own_job(jid, u)
    if r["status"] != "done": raise HTTPException(409, "只有已完成的视频可以重绘单个分镜")
    res = json.loads(r["result"] or "{}"); s = res.get("script")
    if not s or not 0 <= idx < len(s["scenes"]): raise HTTPException(400, "分镜不存在")
    with CREATE_LOCK:
        qi = quota_info(u)
        if qi["quota"] is not None:
            after = qi["jobs_today"] + math.ceil((qi["regens_today"] + 1) / REGEN_PER_QUOTA)
            if after > qi["quota"]:
                raise HTTPException(429, f"今日额度不足：每 {REGEN_PER_QUOTA} 次单镜重绘折算 1 次生成，请明天再来或升级会员")
        with db() as c:
            check_busy(c, u, exclude=jid)
            if body.narration is not None:
                _apply_scene(s["scenes"][idx], SceneEdit(narration=body.narration, narration_en=body.narration_en, image_prompt=body.image_prompt))
            elif body.image_prompt is not None:
                s["scenes"][idx]["image_prompt"] = body.image_prompt.strip()[:600]
            c.execute("INSERT INTO regens(user_id,job_id,scene,day,created) VALUES(?,?,?,?,?)", (u["id"], jid, idx, today(), time.time()))
            c.execute("UPDATE jobs SET status='queued', phase='regen', regen=?, progress=0, message=?, result=? WHERE id=?",
                      (json.dumps([idx]), f"排队重绘第{idx+1}个分镜并重新合成", json.dumps(res, ensure_ascii=False), jid))
    Q.put(jid); return get(jid, u)

# ---------------- 会员套餐与订单 ----------------
@app.get("/api/plans")
def plans(req: Request):
    cfg = plans_config()
    return {"free_daily_quota": cfg.get("free_daily_quota", DAILY_QUOTA), "plans": cfg["plans"],
            "providers": [{"id": p.id, "name": p.name} for p in payments.enabled() if p.configured()],
            "regen_per_quota": REGEN_PER_QUOTA}

class OrderReq(BaseModel):
    plan: str
    provider: str

def grant_plan(c, uid, plan_id, days):
    u = c.execute("SELECT plan, plan_expires FROM users WHERE id=?", (uid,)).fetchone()
    base = u["plan_expires"] if (u["plan"] == plan_id and (u["plan_expires"] or 0) > time.time()) else time.time()
    exp = base + days * 86400
    c.execute("UPDATE users SET plan=?, plan_expires=? WHERE id=?", (plan_id, exp, uid)); return exp

def mark_paid(oid, trade_no):
    with LOCK, db() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o: raise HTTPException(404, "订单不存在")
        if o["status"] == "paid": return o
        c.execute("UPDATE orders SET status='paid', paid_at=?, trade_no=? WHERE id=?", (time.time(), trade_no, oid))
        grant_plan(c, o["user_id"], o["plan"], o["days"])
        return o

@app.post("/api/orders")
def create_order(o: OrderReq, req: Request, u=Depends(current_user)):
    plan = find_plan(o.plan); prov = payments.get(o.provider)
    if not plan: raise HTTPException(404, "套餐不存在")
    if not prov or not prov.configured(): raise HTTPException(400, "该支付方式未开通")
    oid = time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(4)
    order = {"id": oid, "user_id": u["id"], "plan": plan["id"], "plan_name": plan["name"], "amount_cents": int(plan["price_cents"]),
             "days": int(plan["days"]), "provider": prov.id}
    with db() as c:
        c.execute("INSERT INTO orders(id,user_id,plan,plan_name,amount_cents,days,provider,status,created) VALUES(?,?,?,?,?,?,?,'pending',?)",
                  (oid, u["id"], plan["id"], plan["name"], order["amount_cents"], order["days"], prov.id, time.time()))
    try:
        pay = prov.create(order, str(req.base_url))
    except NotImplementedError as e:
        with db() as c: c.execute("UPDATE orders SET status='closed', note=? WHERE id=?", (str(e), oid))
        raise HTTPException(501, str(e))
    return {"order_id": oid, "amount_cents": order["amount_cents"], "pay": pay}

@app.get("/api/orders")
def my_orders(u=Depends(current_user)):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT id,plan_name,amount_cents,days,provider,status,created,paid_at FROM orders WHERE user_id=? ORDER BY created DESC LIMIT 50", (u["id"],))]

@app.post("/api/pay/mock/{oid}/complete")
def mock_complete(oid: str, u=Depends(current_user)):
    if not payments.get("mock"): raise HTTPException(404, "模拟支付未启用")
    with db() as c: o = c.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, u["id"])).fetchone()
    if not o or o["provider"] != "mock": raise HTTPException(404, "订单不存在")
    mark_paid(oid, "MOCK-" + secrets.token_hex(6)); return {"ok": True, **quota_info(current_user_by_id(u["id"]))}

def current_user_by_id(uid):
    with db() as c: return dict(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

@app.post("/api/pay/notify/{provider}")
async def pay_notify(provider: str, req: Request):
    prov = payments.get(provider)
    if not prov or provider == "mock": raise HTTPException(404)
    try:
        oid, trade_no = prov.verify_notify(await req.body(), req.headers)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    mark_paid(oid, trade_no); return Response("success")

@app.get("/pricing")
def pricing_page(): return FileResponse(os.path.join(BASE, "static", "pricing.html"))

# ---------------- 管理 ----------------
@app.get("/api/admin/users")
def admin_users(a=Depends(admin_user)):
    with db() as c:
        rows = c.execute("""SELECT u.id,u.username,u.is_admin,u.quota,u.created,u.plan,u.plan_expires,
            (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id AND j.day=? AND j.status NOT IN ('error','cancelled')) today_used,
            (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id) total_jobs FROM users u ORDER BY u.id""", (today(),)).fetchall()
    cfg = plans_config()
    return {"default_quota": cfg.get("free_daily_quota", DAILY_QUOTA), "plans": cfg["plans"], "users": [dict(r) for r in rows]}

class PlanGrant(BaseModel):
    plan: str | None = None   # None = 取消会员
    days: int = 30

@app.post("/api/admin/users/{uid}/plan")
def admin_grant(uid: int, g: PlanGrant, a=Depends(admin_user)):
    with db() as c:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone(): raise HTTPException(404, "用户不存在")
        if g.plan is None:
            c.execute("UPDATE users SET plan=NULL, plan_expires=NULL WHERE id=?", (uid,)); return {"ok": True}
        if not find_plan(g.plan): raise HTTPException(404, "套餐不存在")
        if not 1 <= g.days <= 3650: raise HTTPException(400, "天数需为 1-3650")
        exp = grant_plan(c, uid, g.plan, g.days)
        c.execute("INSERT INTO orders(id,user_id,plan,plan_name,amount_cents,days,provider,status,created,paid_at,note) VALUES(?,?,?,?,0,?,'admin','paid',?,?,?)",
                  ("ADM" + time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3), uid, g.plan, find_plan(g.plan)["name"], g.days, time.time(), time.time(), f"管理员 {a['username']} 手动开通"))
    return {"ok": True, "plan_expires": exp}

class PlanItem(BaseModel):
    id: str
    name: str
    price_cents: int
    days: int
    daily_quota: int | None = None   # None = 不限
    desc: str = ""

class PlansCfg(BaseModel):
    free_daily_quota: int
    plans: list[PlanItem]

@app.get("/api/admin/plans")
def admin_get_plans(a=Depends(admin_user)): return plans_config()

@app.put("/api/admin/plans")
def admin_put_plans(cfg: PlansCfg, a=Depends(admin_user)):
    if not 0 <= cfg.free_daily_quota <= 1000: raise HTTPException(400, "免费配额需在 0-1000 之间")
    ids = set()
    for p in cfg.plans:
        if not re.fullmatch(r"[a-z0-9_]{1,20}", p.id) or p.id in ids or p.id == "free": raise HTTPException(400, f"套餐 ID 无效或重复：{p.id}")
        ids.add(p.id)
        if not (0 <= p.price_cents <= 10_000_000 and 1 <= p.days <= 3650 and (p.daily_quota is None or 0 <= p.daily_quota <= 1000) and 1 <= len(p.name) <= 20):
            raise HTTPException(400, f"套餐参数无效：{p.name}")
    data = cfg.model_dump()
    with db() as c: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('plans',?)", (json.dumps(data, ensure_ascii=False),))
    return data

@app.post("/api/admin/plans/reset")
def admin_reset_plans(a=Depends(admin_user)):
    with db() as c: c.execute("DELETE FROM settings WHERE key='plans'")
    return plans_config()

@app.get("/api/admin/orders")
def admin_orders(a=Depends(admin_user)):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT o.*, u.username FROM orders o LEFT JOIN users u ON u.id=o.user_id ORDER BY o.created DESC LIMIT 100")]

class QuotaReq(BaseModel):
    quota: int | None = None  # None = 恢复默认

@app.post("/api/admin/users/{uid}/quota")
def set_quota(uid: int, q: QuotaReq, a=Depends(admin_user)):
    if q.quota is not None and not 0 <= q.quota <= 1000: raise HTTPException(400, "配额需在0-1000之间")
    with db() as c:
        if c.execute("UPDATE users SET quota=? WHERE id=?", (q.quota, uid)).rowcount == 0: raise HTTPException(404, "用户不存在")
    return {"ok": True}

@app.get("/admin")
def admin_page(): return FileResponse(os.path.join(BASE, "static", "admin.html"))
@app.get("/login")
def login_page(): return FileResponse(os.path.join(BASE, "static", "login.html"))

app.mount("/", StaticFiles(directory=os.path.join(BASE, "static"), html=True), name="static")
