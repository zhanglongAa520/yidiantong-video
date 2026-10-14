# 🎨 抖音AI科普/成语短视频创作工作台 (AI Video Generator)

> 一站式自媒体短视频自动化创作利器：输入主题或成语典故，全自动生成 **1280x720 60FPS 高清成片** + **专业普通话旁白** + **动态居中字幕** + **抖音爆款发布物料（标题/描述/话题）**！

---

## ✨ 核心特性

- 🎯 **双赛道精准定位**：
  - **🧸 3~8岁 幼儿童趣启蒙**：拟人化童话比喻、生动趣味日常，搭配温馨彩铅儿童绘本画风；
  - **📜 中国成语 奇趣硬核溯源**：典籍考据与科学新解，搭配古风传统写意水墨长卷画风（山水烟雨、扁舟古人、宣纸微瑕质感）。
- ⚡ **阿里百炼全家桶深度原生适配**：
  - **剧本与物料**：`qwen-plus` 深度结合主题生成 60 秒分镜与专属抖音发布文案；
  - **超清水墨/绘本插画**：`qwen-image-2.0` 真实文生图（16:9 画幅、无水印）；
  - **高质音色配音**：`qwen3-tts-flash`（Cherry 芊悦音色），支持自动回退至 edge-tts。
- 📐 **自适应居中排版算法**：
  - 动态计算主副标题字号（38~76px），内置中文语义标点与虚词智能断句，标题居中对称，**彻底杜绝文字撑出画面**。
- 🛡️ **生图防风控自愈机制**：
  - 移除任何程序占位简图，分镜 100% 真实调用百炼 API 生成；
  - 若触发内容安全审核（`DataInspectionFailed`），立即激活大模型自动重写为合规儿童绘本/古风水墨描述并分层重试保底。
- 📋 **抖音发布助手一键直达**：
  - 爆款标题、作品看点描述、热门话题标签一键复制，右上角直达抖音网页端发布。
- 💻 **现代化统一设计语言**：
  - 创作工作台、登录注册中心与管理员用户配额控制台深度对齐现代化卡片式视觉风格；
  - 支持成片在线播放、下载、macOS 访达一键定位及作品一键重新生成。

---

## 🛠️ 技术架构

- **后端引擎**：Python 3.10+、FastAPI、Uvicorn、SQLite (WAL 模式)
- **多媒体处理**：FFmpeg (Ken Burns 动态推镜缩放、drawtext 动态字幕叠加、AAC 音频合成)
- **模型接入**：阿里云百炼 DashScope API (qwen-plus, qwen-image-2.0, qwen3-tts-flash) / OpenAI 兼容协议
- **前端交互**：原生现代化响应式 HTML5 / CSS3 / Vanilla JavaScript

---

## 🚀 快速开始与本地运行

### 1. 系统依赖安装

#### macOS 系统
```bash
# 1. 安装 FFmpeg（建议安装完整版以支持 drawtext 等滤镜）
brew install ffmpeg-full

# 2. 检查中文字体（macOS 默认自带 STHeiti 或 PingFang）
fc-list :lang=zh
```

#### Ubuntu / Debian 系统
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg fonts-noto-cjk
```

---

### 2. 克隆代码与虚拟环境准备

```bash
git clone https://github.com/zhanglongAa520/idiom-video-app.git
cd idiom-video-app

# 创建并激活 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install fastapi uvicorn requests edge-tts pillow bcrypt
```

---

### 3. 配置环境变量

在项目根目录下创建 `.env` 文件（该文件已加入 `.gitignore`，切勿提交至代码库）：

```env
# ---------------- 管理员与系统配置 ----------------
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_strong_password_here
DAILY_QUOTA=3
PORT=8080
WORKERS=1

# ---------------- 阿里云百炼大模型配置 ----------------
# 大模型脚本生成 (qwen-plus)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_MODEL=qwen-plus

# 图像生成 (qwen-image-2.0 原生同步接口)
IMAGE_PROVIDER=qwen
IMAGE_MODEL=qwen-image-2.0
IMAGE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
IMAGE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
IMAGE_SIZE=1280*720
IMAGE_WATERMARK=false

# 语音合成 (qwen3-tts-flash)
TTS_PROVIDER=qwen
VOICE_MODEL=qwen3-tts-flash
TTS_VOICE=Cherry
TTS_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TTS_BASE_URL=https://dashscope.aliyuncs.com/api/v1

# ---------------- 字幕字体路径配置 ----------------
# macOS 默认中文字体路径：
CJK_FONT="/System/Library/Fonts/STHeiti Medium.ttc"
# Linux 默认 Noto 字体路径：
# CJK_FONT="/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

# ---------------- 网络代理配置（可选，如在国内直连百炼则无需配置） ----------------
# HTTP_PROXY=http://127.0.0.1:6152
# HTTPS_PROXY=http://127.0.0.1:6152
```

---

### 4. 启动服务

```bash
# 给脚本添加执行权限
chmod +x run.sh

# 启动服务
./run.sh
```

打开浏览器访问：**`http://localhost:8080`** 即可进入创作工作台！

---

## 🌐 生产服务器部署文档 (Ubuntu / Debian / CentOS)

### 方案 A：使用 Systemd 守护进程常驻运行

1. **将项目部署到服务器**（例如部署在 `/var/www/idiom-video-app`）：
   ```bash
   sudo mkdir -p /var/www/idiom-video-app
   sudo chown -R $USER:$USER /var/www/idiom-video-app
   git clone https://github.com/zhanglongAa520/idiom-video-app.git /var/www/idiom-video-app
   cd /var/www/idiom-video-app
   python3 -m venv .venv
   source .venv/bin/activate
   pip install fastapi uvicorn requests edge-tts pillow bcrypt
   ```

2. **创建 Systemd 服务文件**：
   ```bash
   sudo nano /etc/systemd/system/idiom-video.service
   ```
   写入以下配置：
   ```ini
   [Unit]
   Description=Idiom & Science AI Video App
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/var/www/idiom-video-app
   EnvironmentFile=/var/www/idiom-video-app/.env
   ExecStart=/var/www/idiom-video-app/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **启动并设置开机自启**：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable idiom-video
   sudo systemctl start idiom-video
   sudo systemctl status idiom-video
   ```

---

### 方案 B：配置 Nginx 反向代理与 SSL 证书

在 `/etc/nginx/sites-available/video.yourdomain.com` 中创建 Nginx 虚拟主机配置：

```nginx
server {
    listen 80;
    server_name video.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name video.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/video.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/video.yourdomain.com/privkey.pem;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 支持长轮询与视频切片流传输
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

测试并重载 Nginx：
```bash
sudo nginx -t
sudo systemctl reload nginx
```

并在 `.env` 中设置：
```env
COOKIE_SECURE=1
TRUST_PROXY=1
```

---

## ⚙️ 核心环境变量清单

| 变量名 | 必填 | 默认值 | 说明 |
| :--- | :---: | :---: | :--- |
| `ADMIN_USERNAME` | 是 | `admin` | 管理员用户名（启动时自动创建或更新密码） |
| `ADMIN_PASSWORD` | 是 | - | 管理员密码（初始强密码） |
| `DAILY_QUOTA` | 否 | `3` | 普通注册用户每日视频生成次数上限 |
| `LLM_API_KEY` | 是 | - | 阿里云百炼 API-KEY（用于生成剧本及发布物料） |
| `LLM_MODEL` | 否 | `qwen-plus` | 大语言模型编号（推荐 `qwen-plus`） |
| `IMAGE_PROVIDER` | 否 | `qwen` | 图像提供方（`qwen` / `wanx` / `openai`） |
| `IMAGE_MODEL` | 否 | `qwen-image-2.0` | 生图模型名称（推荐 `qwen-image-2.0`，无水印且速度快） |
| `IMAGE_SIZE` | 否 | `1280*720` | 生图输出分辨率 |
| `IMAGE_WATERMARK`| 否 | `false` | 是否添加百炼官方水印（建议 `false`） |
| `TTS_PROVIDER` | 否 | `qwen` | 配音驱动（`qwen` / `edge-tts`） |
| `VOICE_MODEL` | 否 | `qwen3-tts-flash`| 通义配音模型 |
| `TTS_VOICE` | 否 | `Cherry` | 音色选择（`Cherry` 芊悦、`Ethan` 等） |
| `CJK_FONT` | 是 | - | 系统中文字体文件绝对路径（用于 FFmpeg 字幕渲染） |
| `PORT` | 否 | `8080` | 本地服务运行端口 |
| `WORKERS` | 否 | `1` | 后台并发视频渲染 Worker 线程数 |
| `COOKIE_SECURE` | 否 | `0` | 开启 HTTPS 时设置为 `1` |
| `TRUST_PROXY` | 否 | `0` | 位于 Nginx 反代后设为 `1`，正确获取客户端 IP 进行防刷限流 |

---

## ❓ 常见问题排查 (FAQ)

### 1. 生成视频时报错：`drawtext: No such filter`
- **原因**：系统的 FFmpeg 编译时未开启 `--enable-libfreetype` 或 `--enable-libharfbuzz`。
- **解决**：
  - macOS：请使用 `brew install ffmpeg-full` 并确保 PATH 包含 `/opt/homebrew/opt/ffmpeg-full/bin`；
  - Ubuntu：直接 `sudo apt install ffmpeg` 默认已自带 `drawtext` 滤镜支持。

### 2. 生图出现敏感词拦截 (`DataInspectionFailed`) 怎么办？
- **解决**：无需手动干预。系统内建大模型自愈重试流水线（`sanitize_prompt_via_llm`），会自动调用 `qwen-plus` 将提示词重写为纯正可爱的全年龄儿童绘本或传统诗意山水水墨风，并重试 3 次，保证 100% 真实调用百炼 API 绘图，绝不退化为占位简图。

### 3. 字幕出现乱码或方块口口口？
- **原因**：`CJK_FONT` 环境变量指向的字体路径不正确或文件不存在。
- **解决**：检查字体文件是否存在，例如 Ubuntu 执行 `ls /usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc`，并将正确的完整路径填入 `.env` 的 `CJK_FONT`。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。欢迎贡献代码与提交 Issue！
