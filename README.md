# 成语·科普 短视频生成器（原型）

输入成语或生活常识问题 → 自动生成约 1 分钟、1280x720 H.264 MP4：标题卡 + 5-6 个场景插图（Ken Burns 推镜）+ 女声普通话配音（edge-tts `zh-CN-XiaoxiaoNeural`）+ 烧录简体字幕。

## 运行
```bash
pip install fastapi uvicorn requests edge-tts pillow bcrypt   # 另需 ffmpeg 与中文字体（Noto CJK）
./run.sh                 # 默认端口 8080，可用 PORT=xxxx 修改
```
打开 http://localhost:8080 ，先注册/登录。

可在项目目录放一个 `.env`（已 gitignore，切勿提交）供 `run.sh` 读取，例如：
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请换成强密码
DAILY_QUOTA=3
```

## 账号与限额
- SQLite（默认 `app.db`，已 gitignore）保存用户、会话、任务；服务重启后任务列表不丢失，中断的任务自动重新排队。
- 开放注册（用户名 3-20 位，密码 8-72 位），密码用 bcrypt 哈希；登录后下发随机会话令牌 Cookie（HttpOnly、SameSite=Lax，`COOKIE_SECURE=1` 时加 Secure）。
- 生成/状态/视频/配置接口均需登录；普通用户只能看到自己的任务和视频（访问他人任务返回 404）。
- 每人每日生成配额 `DAILY_QUOTA`（默认 3，按 `QUOTA_TZ` 自然日计算，失败任务不计），页面右上角显示剩余次数；每人同时只能有 1 个进行中的任务。
- 管理员：启动时按 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 创建（或重置密码），不限次数、无并发限制，可访问 `/admin` 查看用户并单独调整每日配额（留空=默认）。
- 防暴力破解：同一 IP 在 `LOGIN_WINDOW_SEC` 内失败 `LOGIN_MAX_ATTEMPTS` 次后暂时拒绝登录/注册（内存计数，重启清零）。在反向代理后面请设置 `TRUST_PROXY=1` 以使用 `X-Forwarded-For`。

## 结构
- `app.py`：FastAPI 接口 + 内存任务队列（后台线程，`WORKERS` 控制并发）
  - `POST /api/jobs` `{topic, kind: chengyu|kepu, style: ink|kids}` → 任务
  - `GET /api/jobs/{id}` 进度/状态/脚本；`GET /api/jobs/{id}/video[?download=1]`
  - `GET /api/config` 当前启用了哪些服务商
- `pipeline.py`：脚本 → 图片 → 配音 → ffmpeg 合成，服务商可插拔
- `static/index.html`：主页面；`static/login.html` 登录/注册；`static/admin.html` 用户管理
- `builtin/`：内置“刻舟求剑”脚本对应的水墨插图
- `output/`：生成的视频 `{id}.mp4` 及中间文件

## 接入 API Key（环境变量）
| 变量 | 作用 |
|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 任意 OpenAI 兼容 `/chat/completions` 接口（OpenAI、DeepSeek、通义、xAI 等）。例：`https://api.deepseek.com/v1` + `deepseek-chat` |
| `IMAGE_API_KEY` / `IMAGE_BASE_URL` / `IMAGE_MODEL` / `IMAGE_SIZE` | OpenAI 兼容 `/images/generations`（默认 `https://api.openai.com/v1`、`gpt-image-1`、`1536x1024`），支持返回 b64_json 或 url |
| `TTS_VOICE` | edge-tts 音色，默认 `zh-CN-XiaoxiaoNeural` |
| `CJK_FONT` | 字幕字体路径 |
| `OUTPUT_DIR`, `PORT`, `WORKERS` | 输出目录 / 端口 / 全局并发 |
| `DB_PATH` | SQLite 路径，默认 `app.db` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（启动时创建/重置） |
| `DAILY_QUOTA` | 每人每日生成次数，默认 3 |
| `QUOTA_TZ` | 配额按哪个时区的自然日计算，默认 `Asia/Shanghai` |
| `SESSION_DAYS` | 登录有效天数，默认 7 |
| `COOKIE_SECURE` | HTTPS 部署时设为 `1` |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SEC` | 登录限流，默认 15 分钟内 10 次 |
| `TRUST_PROXY` | 反代后设为 `1`，按 X-Forwarded-For 识别 IP |

```bash
LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... IMAGE_API_KEY=sk-... ./run.sh
```

### 无 Key 回退
- 脚本：“刻舟求剑”用内置手写脚本；其它主题用模板脚本（通用句式，内容较空泛）。
- 图片：“刻舟求剑”+古风水墨用内置插图；其它用程序生成的水墨/绘本风占位画（山水小舟）。
- 配音：edge-tts 需联网；失败时自动静音并按字数估算时长。
- 任何 API 调用失败都会自动回退，不会中断任务。

## 公网部署
1. 云服务器（≥2 核 4G），装 `ffmpeg fonts-noto-cjk python3`，按上面装依赖。
2. 用 systemd 或 `docker` 常驻运行 `run.sh`；前面加 Nginx/Caddy 反代 + HTTPS（Caddy：`yourdomain.com { reverse_proxy localhost:8080 }`）。
3. 公网务必：设置强 `ADMIN_PASSWORD`、`COOKIE_SECURE=1`、`TRUST_PROXY=1`（有反代时），并备份 `app.db`。
4. 生产化建议：多实例时把队列换成 Redis + RQ/Celery、SQLite 换 PostgreSQL；视频放对象存储（S3/OSS）+ CDN；定时清理 `output/`。
5. 也可用 Render / Railway / Fly.io 等容器平台（需在镜像中装 ffmpeg 和中文字体）。
