# 成语·科普 短视频生成器（原型）

输入成语或生活常识问题 → 自动生成约 1 分钟、1280x720 H.264 MP4：标题卡 + 5-6 个场景插图（Ken Burns 推镜）+ 女声普通话配音（edge-tts `zh-CN-XiaoxiaoNeural`）+ 烧录简体字幕。

## 运行
```bash
pip install fastapi uvicorn requests edge-tts pillow   # 另需 ffmpeg 与中文字体（Noto CJK）
./run.sh                 # 默认端口 8080，可用 PORT=xxxx 修改
```
打开 http://localhost:8080

## 结构
- `app.py`：FastAPI 接口 + 内存任务队列（后台线程，`WORKERS` 控制并发）
  - `POST /api/jobs` `{topic, kind: chengyu|kepu, style: ink|kids}` → 任务
  - `GET /api/jobs/{id}` 进度/状态/脚本；`GET /api/jobs/{id}/video[?download=1]`
  - `GET /api/config` 当前启用了哪些服务商
- `pipeline.py`：脚本 → 图片 → 配音 → ffmpeg 合成，服务商可插拔
- `static/index.html`：前端
- `builtin/`：内置“刻舟求剑”脚本对应的水墨插图
- `output/`：生成的视频 `{id}.mp4` 及中间文件

## 接入 API Key（环境变量）
| 变量 | 作用 |
|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 任意 OpenAI 兼容 `/chat/completions` 接口（OpenAI、DeepSeek、通义、xAI 等）。例：`https://api.deepseek.com/v1` + `deepseek-chat` |
| `IMAGE_API_KEY` / `IMAGE_BASE_URL` / `IMAGE_MODEL` / `IMAGE_SIZE` | OpenAI 兼容 `/images/generations`（默认 `https://api.openai.com/v1`、`gpt-image-1`、`1536x1024`），支持返回 b64_json 或 url |
| `TTS_VOICE` | edge-tts 音色，默认 `zh-CN-XiaoxiaoNeural` |
| `CJK_FONT` | 字幕字体路径 |
| `OUTPUT_DIR`, `PORT`, `WORKERS` | 输出目录 / 端口 / 并发 |

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
3. 生产化建议：任务状态目前在内存中，重启会丢失 → 换 Redis + RQ/Celery；视频放对象存储（S3/OSS）+ CDN；加登录/限流（防止刷 API 费用）、定时清理 `output/`。
4. 也可用 Render / Railway / Fly.io 等容器平台（需在镜像中装 ffmpeg 和中文字体）。
