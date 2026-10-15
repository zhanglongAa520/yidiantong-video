<div align="center">

# 🎨 成语·科普 AI 短视频工作台

**输入一个成语或科普问题，一键生成约 1 分钟的配音字幕短视频，并同时产出中文版 + 英文出海版和抖音 / TikTok 发布文案。**

[中文](#-项目简介) · [English](#-english) · [MIT License](LICENSE)

<img src="docs/demo.gif" alt="刻舟求剑 演示" width="560">

<sub>演示：内置成语《刻舟求剑》古风水墨成片（节选 10 秒）</sub>

</div>

---

## 📖 项目简介

面向自媒体创作者的短视频自动化工具。输入主题后，系统自动完成 **分镜剧本 → 插画 → 旁白配音 → Ken Burns 推镜 + 字幕合成**，输出 1280×720 H.264 MP4，并附带可直接复制的发布物料（爆款标题、作品描述、话题标签）。

两条内容赛道：

| 赛道 | 受众 | 画风 |
| --- | --- | --- |
| 🧸 幼儿童趣启蒙 | 3~8 岁 | 温馨彩铅 / 水彩儿童绘本 |
| 📜 中国成语奇趣溯源 | 少年 / 成人 | 古风写意水墨（山水烟雨、扁舟古人、宣纸质感） |

## ✨ 功能特性

- **全自动成片**：标题卡 + 5~6 个分镜，缓慢推镜动画，逐句烧录字幕，约 60 秒。
- **中英独立双版本**：一次生成插画，同时压制「纯中文版」和「英文出海版」（英文配音、英文字幕与标题卡）；也可只生成其中一种。再次生成同一主题会继承已有插画，保证两版画面一致。
- **抖音 / TikTok 发布助手**：自动生成中英文标题、描述和话题标签，一键复制。
- **内置选题库**：幼儿 80 题、成语 300+ 题、科普 300 题，自动过滤已创作的选题。
- **可插拔 AI 服务**：剧本用 OpenAI 兼容大模型（默认阿里百炼 `qwen-plus`）；插画支持百炼 `qwen-image` / 万相 `wanx` / OpenAI 兼容接口；配音用通义 `qwen3-tts-flash`，失败自动回退到免费的 edge-tts（中文 `zh-CN-XiaoxiaoNeural`，英文 `en-US-JennyNeural`）。
- **生图风控自愈**：遇到内容审核拦截时，自动用大模型改写提示词并分级重试。
- **无 Key 也能试用**：内置《刻舟求剑》完整剧本与水墨插画；其它主题使用模板剧本 + 程序生成的占位插画，配音走 edge-tts。
- **账号与限额**：开放注册、bcrypt 密码哈希、HttpOnly 会话 Cookie；每人每日生成配额（默认 3 次）、每人同时 1 个任务；登录按 IP 限流防暴力破解。
- **管理后台**：管理员不限次数，可查看所有用户用量并单独调整每日配额。
- **任务持久化**：SQLite（WAL）保存用户与任务，重启不丢失，中断任务自动重新排队。

## 🖼️ 界面截图

| 登录 / 注册 | 创作工作台 |
| :---: | :---: |
| <img src="docs/screenshots/login.png" width="420"> | <img src="docs/screenshots/workspace.png" width="420"> |
| **生成进度** | **成片与发布物料** |
| <img src="docs/screenshots/progress.png" width="420"> | <img src="docs/screenshots/result.png" width="420"> |

<details><summary>管理员：用户与配额管理</summary>

<img src="docs/screenshots/admin.png" width="720">
</details>

<sub>截图使用临时数据库和演示账号，在未配置任何 API Key 的回退模式下截取。</sub>

## 🎬 示例成片

《刻舟求剑》内置水墨版（中文配音 + 字幕）关键帧：

| | | |
| :---: | :---: | :---: |
| <img src="docs/frames/kezhou_8.jpg" width="280"> | <img src="docs/frames/kezhou_20.jpg" width="280"> | <img src="docs/frames/kezhou_30.jpg" width="280"> |
| <img src="docs/frames/kezhou_38.jpg" width="280"> | <img src="docs/frames/kezhou_50.jpg" width="280"> | |

## 🚀 快速开始

### 1. 系统依赖

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y python3 python3-venv ffmpeg fonts-noto-cjk
# macOS（需带 drawtext 滤镜的 ffmpeg）
brew install ffmpeg-full
```

### 2. 安装

```bash
git clone https://github.com/zhanglongAa520/idiom-video-app.git
cd idiom-video-app
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn requests edge-tts pillow bcrypt
```

### 3. 配置 `.env`（已在 `.gitignore` 中，切勿提交）

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请换成强密码
DAILY_QUOTA=3

# 以下均为可选；不填则进入免 Key 回退模式
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxxx
LLM_MODEL=qwen-plus
IMAGE_PROVIDER=qwen
IMAGE_API_KEY=sk-xxxx
TTS_PROVIDER=qwen
TTS_API_KEY=sk-xxxx

# 字幕字体：Linux 默认如下；macOS 可用 "/System/Library/Fonts/STHeiti Medium.ttc"
CJK_FONT=/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc
```

### 4. 启动

```bash
chmod +x run.sh && ./run.sh      # 默认 http://localhost:8080
```

注册账号后即可开始创作；用 `ADMIN_USERNAME` 登录可访问 `/admin`。

## ⚙️ 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| **账号与系统** | | |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | – | 启动时创建管理员（已存在则重置密码） |
| `DAILY_QUOTA` | `3` | 普通用户每日生成次数（失败任务不计） |
| `QUOTA_TZ` | `Asia/Shanghai` | 配额按该时区自然日重置 |
| `SESSION_DAYS` | `7` | 登录有效期（天） |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SEC` | `10` / `900` | 同一 IP 在窗口内失败次数上限 |
| `COOKIE_SECURE` | `0` | HTTPS 部署时设为 `1` |
| `TRUST_PROXY` | `0` | 位于反向代理后设为 `1`（使用 `X-Forwarded-For` 识别 IP） |
| `DB_PATH` | `app.db` | SQLite 数据库路径 |
| `OUTPUT_DIR` | `output/` | 成片与中间文件目录 |
| `PORT` / `WORKERS` | `8080` / `1` | 端口 / 后台渲染线程数 |
| **剧本（大模型）** | | |
| `LLM_BASE_URL` / `LLM_API_KEY` | – | 任意 OpenAI 兼容 `/chat/completions` 接口 |
| `LLM_MODEL` | `qwen-plus` | 模型名称 |
| **插画** | | |
| `IMAGE_PROVIDER` | `qwen` | `qwen` / `wanx` / `openai` |
| `IMAGE_API_KEY` | – | 生图 Key；不填则使用占位插画 |
| `IMAGE_BASE_URL` | 视提供方 | 百炼默认 `https://dashscope.aliyuncs.com/api/v1`，OpenAI 默认 `https://api.openai.com/v1` |
| `IMAGE_MODEL` | 视提供方 | `qwen-image-2.0` / `wan2.2-t2i-flash` / `gpt-image-1` |
| `IMAGE_SIZE` | 视提供方 | 如 `1280*720`（百炼）或 `1536x1024`（OpenAI） |
| `IMAGE_WATERMARK` | `false` | 是否保留百炼水印 |
| **配音** | | |
| `TTS_PROVIDER` | `qwen` | `qwen` 失败时自动回退 edge-tts |
| `TTS_API_KEY` | – | 通义 TTS Key（缺省依次使用 `IMAGE_API_KEY`、`LLM_API_KEY`） |
| `TTS_BASE_URL` | `https://dashscope.aliyuncs.com/api/v1` | 通义 TTS 接口地址 |
| `VOICE_MODEL` / `TTS_VOICE` | `qwen3-tts-flash` / `Cherry` | 通义配音模型 / 音色 |
| `EDGE_TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 中文音色（英文固定 `en-US-JennyNeural`） |
| `CJK_FONT` | Noto Serif CJK | 字幕字体文件路径 |

## 🌐 部署

1. **服务器**：建议 ≥2 核 4G，安装 ffmpeg 与中文字体，按「快速开始」安装依赖。
2. **常驻运行（systemd）**：

   ```ini
   [Service]
   WorkingDirectory=/var/www/idiom-video-app
   EnvironmentFile=/var/www/idiom-video-app/.env
   ExecStart=/var/www/idiom-video-app/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080
   Restart=always
   ```

3. **HTTPS 反向代理**：Nginx（`proxy_pass http://127.0.0.1:8080; proxy_buffering off; proxy_read_timeout 300s;` 并转发 `X-Forwarded-For`）或 Caddy（`video.example.com { reverse_proxy localhost:8080 }`）。
4. **公网安全清单**：强 `ADMIN_PASSWORD`、`COOKIE_SECURE=1`、反代后 `TRUST_PROXY=1`、定期备份 `app.db`、定时清理 `output/`。
5. **扩展**：多实例部署时可将内存队列换成 Redis + RQ/Celery，SQLite 换 PostgreSQL，成片放对象存储 + CDN。

> 「在访达中定位」按钮仅在 macOS 本机运行时可用。

## ❓ 常见问题

- **`drawtext: No such filter`**：ffmpeg 缺少 freetype。macOS 用 `ffmpeg-full`，Ubuntu 的 `apt install ffmpeg` 已包含。
- **字幕显示方块**：`CJK_FONT` 路径不对，指向一个存在的中文字体文件即可。
- **生图被审核拦截（`DataInspectionFailed`）**：系统会自动改写提示词并重试，最多 3 次。

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 🌏 English

**Idiom & Science AI Short-Video Studio** — type a Chinese idiom or a science question and get a ~1-minute, 1280×720 narrated, subtitled video, in a **Chinese version and an English version for global platforms**, plus ready-to-paste Douyin / TikTok titles, descriptions and hashtags.

**Features**
- Automatic pipeline: script → illustrations → narration → Ken Burns motion + burned-in subtitles (FFmpeg).
- Two tracks: kids' science (picture-book style) and Chinese idioms (ink-wash style), with built-in topic libraries.
- Chinese and English versions from one set of illustrations (consistent shots), each with its own voice-over, subtitles and title card.
- Pluggable providers: any OpenAI-compatible LLM; Alibaba Bailian `qwen-image` / `wanx` / OpenAI-compatible image APIs; Qwen TTS with automatic free edge-tts fallback.
- Works without API keys (built-in 刻舟求剑 story; template scripts + procedural placeholder art for other topics).
- Accounts (bcrypt, HttpOnly session cookie), daily per-user quota, 1 concurrent job per user, per-IP login rate limiting, admin page for quotas, SQLite persistence.

**Quick start**
```bash
sudo apt install -y ffmpeg fonts-noto-cjk python3-venv
git clone https://github.com/zhanglongAa520/idiom-video-app.git && cd idiom-video-app
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn requests edge-tts pillow bcrypt
echo "ADMIN_USERNAME=admin" > .env && echo "ADMIN_PASSWORD=change-me" >> .env
./run.sh   # http://localhost:8080
```
See the environment variable table above for API keys and options. For production, run behind an HTTPS reverse proxy with `COOKIE_SECURE=1` and `TRUST_PROXY=1`.

**License:** [MIT](LICENSE) © 2026 zhanglongAa520
