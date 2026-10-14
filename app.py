import os, uuid, queue, threading, time, json, sqlite3, secrets, traceback, datetime, re, subprocess
from collections import defaultdict, deque
from zoneinfo import ZoneInfo
import bcrypt
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pipeline

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
    """将数据库任务记录转换为前端展示所需的标准字典对象，并自动附加抖音发布物料与视频播放链接。"""
    d = dict(r); d["log"] = json.loads(d["log"] or "[]"); res = json.loads(d.pop("result") or "{}"); d.update(res)
    if d["status"] == "done": d["video"] = f"/api/jobs/{d['id']}/video"
    script_obj = d.get("script")
    d["publish_info"] = get_douyin_publish_info(d["topic"], d.get("kind", "chengyu"), d.get("style", "ink"), script_obj)
    d.pop("user_id", None); return d

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
            res = pipeline.build(r["topic"], r["kind"], r["style"], os.path.join(OUT, jid), os.path.join(OUT, f"{jid}.mp4"), prog)
            update_job(jid, status="done", progress=100, message="完成", result=json.dumps(res, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc(); update_job(jid, status="error", message=f"失败：{e}")

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

def quota_info(u):
    q = None if u["is_admin"] else (u["quota"] if u["quota"] is not None else DAILY_QUOTA)
    with db() as c:
        used = c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND day=? AND status!='error'", (u["id"], today())).fetchone()[0]
    return {"quota": q, "used": used, "remaining": None if q is None else max(0, q - used)}

@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"username": u["username"], "is_admin": bool(u["is_admin"]), **quota_info(u)}

# ---------------- 任务 ----------------
class Req(BaseModel):
    topic: str
    kind: str = "chengyu"
    style: str = "ink"
    mode: str | None = None

CREATE_LOCK = threading.Lock()
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
    with CREATE_LOCK:
        qi = quota_info(u)
        if qi["remaining"] is not None and qi["remaining"] <= 0:
            raise HTTPException(429, f"今日生成次数已用完（每日{qi['quota']}次），请明天再来")
        with db() as c:
            if not u["is_admin"] and c.execute("SELECT 1 FROM jobs WHERE user_id=? AND status IN ('queued','running')", (u["id"],)).fetchone():
                raise HTTPException(429, "你已有一个视频正在生成，请等待完成后再提交")
            jid = uuid.uuid4().hex[:12]
            c.execute("INSERT INTO jobs(id,user_id,topic,kind,style,status,progress,message,created,day) VALUES(?,?,?,?,?,'queued',0,?,?,?)",
                      (jid, u["id"], t, r.kind, r.style, f"排队中（前面{Q.qsize()}个）", time.time(), today()))
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
def video(jid: str, download: int = 0, u=Depends(current_user)):
    r = own_job(jid, u); p = os.path.join(OUT, f"{jid}.mp4")
    if not os.path.exists(p): raise HTTPException(404, "视频不存在")
    return FileResponse(p, media_type="video/mp4", filename=f"{r['topic']}.mp4" if download else None)

@app.get("/api/config")
def config(u=Depends(current_user)):
    return {"llm": bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY")), "image": bool(os.getenv("IMAGE_API_KEY")),
            "voice": pipeline.VOICE, "builtin": list(pipeline.BUILTIN)}

class OpenFinderReq(BaseModel):
    id: str

@app.post("/api/open_finder")
def open_finder(req: OpenFinderReq, u=Depends(current_user)):
    """在 macOS 访达中定位并高亮选中的成片视频文件。"""
    job = own_job(req.id, u)
    p = os.path.join(OUT, f"{job['id']}.mp4")
    target = p if os.path.exists(p) else os.path.join(OUT, job['id'])
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

# ---------------- 管理 ----------------
@app.get("/api/admin/users")
def admin_users(a=Depends(admin_user)):
    with db() as c:
        rows = c.execute("""SELECT u.id,u.username,u.is_admin,u.quota,u.created,
            (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id AND j.day=? AND j.status!='error') today_used,
            (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id) total_jobs FROM users u ORDER BY u.id""", (today(),)).fetchall()
    return {"default_quota": DAILY_QUOTA, "users": [dict(r) for r in rows]}

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
