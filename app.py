import os, uuid, queue, threading, time, json, sqlite3, secrets, traceback, datetime, re
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

def job_dict(r):
    d = dict(r); d["log"] = json.loads(d["log"] or "[]"); res = json.loads(d.pop("result") or "{}"); d.update(res)
    if d["status"] == "done": d["video"] = f"/api/jobs/{d['id']}/video"
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

CREATE_LOCK = threading.Lock()
@app.post("/api/jobs")
def create(r: Req, u=Depends(current_user)):
    t = r.topic.strip()
    if not t or len(t) > 40: raise HTTPException(400, "请输入1-40字的主题")
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
