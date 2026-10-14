import os, uuid, queue, threading, time, traceback
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pipeline

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.getenv("OUTPUT_DIR", os.path.join(BASE, "output")); os.makedirs(OUT, exist_ok=True)
app = FastAPI(title="成语/科普 短视频生成器")
JOBS, Q = {}, queue.Queue()

class Req(BaseModel):
    topic: str
    kind: str = "chengyu"   # chengyu | kepu
    style: str = "ink"      # ink | kids

def worker():
    while True:
        jid = Q.get(); j = JOBS[jid]; j["status"] = "running"
        def prog(p, m):
            if p is not None: j["progress"] = min(p, 99)
            j["message"] = m; j["log"].append(m)
        try:
            r = pipeline.build(j["topic"], j["kind"], j["style"], os.path.join(OUT, jid), os.path.join(OUT, f"{jid}.mp4"), prog)
            j.update(r, status="done", progress=100, message="完成", video=f"/api/jobs/{jid}/video")
        except Exception as e:
            traceback.print_exc(); j.update(status="error", message=f"失败：{e}")
for _ in range(int(os.getenv("WORKERS", "1"))): threading.Thread(target=worker, daemon=True).start()

@app.post("/api/jobs")
def create(r: Req):
    t = r.topic.strip()
    if not t or len(t) > 40: raise HTTPException(400, "请输入1-40字的主题")
    if r.kind not in ("chengyu", "kepu") or r.style not in ("ink", "kids"): raise HTTPException(400, "参数错误")
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = dict(id=jid, topic=t, kind=r.kind, style=r.style, status="queued", progress=0,
                     message=f"排队中（前面{Q.qsize()}个）", log=[], created=time.time())
    Q.put(jid); return JOBS[jid]

@app.get("/api/jobs/{jid}")
def get(jid: str):
    if jid not in JOBS: raise HTTPException(404)
    return JOBS[jid]

@app.get("/api/jobs/{jid}/video")
def video(jid: str, download: int = 0):
    p = os.path.join(OUT, f"{jid}.mp4")
    if jid not in JOBS or not os.path.exists(p): raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4", filename=f"{JOBS[jid]['topic']}.mp4" if download else None)

@app.get("/api/config")
def config():
    return {"llm": bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY")), "image": bool(os.getenv("IMAGE_API_KEY")),
            "voice": pipeline.VOICE, "builtin": list(pipeline.BUILTIN)}

app.mount("/", StaticFiles(directory=os.path.join(BASE, "static"), html=True), name="static")
