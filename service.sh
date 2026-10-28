#!/bin/bash
# 成语视频 App 服务管理脚本
# 用法: ./service.sh {start|stop|restart|status|setup}
#   setup  = git pull + 准备 Python 环境（.venv）+ 安装依赖，start 前环境不满足时也会自动执行
set -u
cd "$(dirname "$0")"

# 加载 .env（如果存在，不提交到 git）；剥离 Windows CRLF 避免 source 报错
# 显式传入的环境变量优先于 .env（dotenv 标准语义）
_CLI_PORT="${PORT:-}"; _CLI_PYTHON="${PYTHON:-}"
if [ -f .env ]; then
    set -a
    . <(sed 's/\r$//' .env)
    set +a
fi
[ -n "$_CLI_PORT" ] && PORT="$_CLI_PORT"
[ -n "$_CLI_PYTHON" ] && PYTHON="$_CLI_PYTHON"

PORT="${PORT:-8080}"
PID_FILE=".cache/app.pid"
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/app.log"
VENV_PY=".venv/bin/python"
REQ_FILE="requirements.txt"

mkdir -p .cache "$LOG_DIR"

log() { echo "[service] $*"; }

# ---------- 环境准备 ----------

# git pull（仅当是 git 仓库；失败只警告不阻断，允许离线启动）
do_git_pull() {
    if [ -d .git ]; then
        log "git pull ..."
        local out rc
        out=$(git pull --ff-only 2>&1); rc=$?
        printf '%s\n' "$out" | sed 's/^/[git] /'
        if [ $rc -ne 0 ]; then
            log "警告：git pull 失败（网络或本地有未提交改动），继续用当前代码"
        fi
    else
        log "非 git 仓库，跳过 git pull"
    fi
}

# 项目要求 Python >= 3.10（app.py 使用 `dict | None` 语法；老版本 pip 也装不上 bcrypt 等包）
MIN_PY="3.10"

# 判断解释器版本是否达标
py_version_ok() {
    "$1" - "$MIN_PY" <<'EOF' >/dev/null 2>&1
import sys
minv = tuple(int(x) for x in sys.argv[1].split("."))
sys.exit(0 if sys.version_info[:2] >= minv else 1)
EOF
}

# 解释器是否可用（存在 + 版本达标）
py_usable() {
    local c="$1"
    [ -n "$c" ] || return 1
    command -v "$c" >/dev/null 2>&1 || [ -x "$c" ] || return 1
    py_version_ok "$c"
}

# 找一个版本达标且装了 uvicorn+fastapi 的解释器
# 优先级：显式 PYTHON > ./.venv > PATH 的 python3 > pyenv 各版本（新版优先）
find_python() {
    local cands=() c
    [ -n "${PYTHON:-}" ] && cands+=("$PYTHON")
    [ -x "$VENV_PY" ] && cands+=("$VENV_PY")
    cands+=("python3")
    # pyenv 版本按倒序（新 -> 旧）加入候选
    local p
    for p in $(ls -1d "$HOME"/.pyenv/versions/*/bin/python3 2>/dev/null | sort -rV); do
        [ -x "$p" ] && cands+=("$p")
    done
    for c in "${cands[@]}"; do
        if py_usable "$c" && "$c" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
            printf '%s\n' "$c"; return 0
        fi
    done
    return 1
}

# 列出探测到的解释器及其版本，便于诊断
report_pythons() {
    local c v
    for c in "${PYTHON:-}" "$VENV_PY" python3 $(ls -1d "$HOME"/.pyenv/versions/*/bin/python3 2>/dev/null | sort -rV) /usr/bin/python3; do
        [ -n "$c" ] || continue
        command -v "$c" >/dev/null 2>&1 || [ -x "$c" ] || continue
        v=$("$c" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null) || continue
        if py_version_ok "$c"; then
            log "  可用：$c ($v)"
        else
            log "  版本过低：$c ($v) < $MIN_PY"
        fi
    done
}

# 准备 .venv 并安装依赖（基础解释器必须 >= MIN_PY，老 venv 自动重建）
setup_venv() {
    local base=""
    if [ -x "$VENV_PY" ]; then
        if py_version_ok "$VENV_PY"; then
            base="$VENV_PY"
        else
            log "现有 .venv 的 Python 版本低于 $MIN_PY，删除重建 ..."
            rm -rf .venv
        fi
    fi
    if [ -z "$base" ]; then
        local c
        for c in python3 $(ls -1d "$HOME"/.pyenv/versions/*/bin/python3 2>/dev/null | sort -rV) /usr/bin/python3; do
            if py_usable "$c" && "$c" -m venv --help >/dev/null 2>&1; then
                base="$c"; break
            fi
        done
        if [ -z "$base" ]; then
            log "错误：找不到 Python >= $MIN_PY 的解释器（app.py 使用新语法，低版本无法运行）。"
            log "探测到的解释器："
            report_pythons
            log "请先安装新版 Python，例如：sudo apt install python3.12 python3.12-venv"
            return 1
        fi
        log "创建虚拟环境 .venv（基于 $base）..."
        "$base" -m venv .venv || { log "错误：venv 创建失败"; return 1; }
    fi
    if [ -f "$REQ_FILE" ]; then
        log "安装依赖 $REQ_FILE ..."
        "$VENV_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
        # .env 可能带死代理（如 macOS Surge）、官方源国内访问慢：失败时绕过代理+阿里云镜像重试
        "$VENV_PY" -m pip install --quiet -r "$REQ_FILE" || {
            log "pip 安装失败，绕过代理并用阿里云镜像重试 ..."
            env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
                "$VENV_PY" -m pip install --quiet \
                -i https://mirrors.aliyun.com/pypi/simple/ \
                -r "$REQ_FILE" \
                || { log "错误：依赖安装失败，检查网络或 pip 源"; return 1; }
        }
    else
        log "无 $REQ_FILE，安装最小依赖 uvicorn+fastapi ..."
        env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
            "$VENV_PY" -m pip install --quiet \
            -i https://mirrors.aliyun.com/pypi/simple/ \
            uvicorn fastapi || { log "错误：依赖安装失败"; return 1; }
    fi
    log "依赖安装完成"
}

# setup 入口：git pull + 依赖环境
do_setup() {
    do_git_pull
    if find_python >/dev/null; then
        log "Python 依赖已就绪：$(find_python)"
    else
        setup_venv || return 1
    fi
    # 附带检查 ffmpeg（视频合成需要，缺了只警告）
    command -v ffmpeg >/dev/null 2>&1 || log "警告：未检测到 ffmpeg，视频合成会失败（Ubuntu: sudo apt install ffmpeg）"
    # 确保静态目录存在（app.py 启动时 mount 需要）
    mkdir -p assets
}

# 解析最终使用的解释器；环境不满足时自动 setup 一次
resolve_python() {
    if PYTHON="$(find_python)"; then
        export PYTHON
        return 0
    fi
    log "未找到可用 Python 环境，自动执行 setup（git pull + 安装依赖）..."
    do_setup || return 1
    if PYTHON="$(find_python)"; then
        export PYTHON
        return 0
    fi
    log "错误：setup 后仍找不到已安装 uvicorn+fastapi 的解释器。"
    log "可手动执行：./service.sh setup 查看详细报错，或 PYTHON=/path/to/python $0 start 显式指定。"
    return 1
}

# ---------- 进程管理 ----------

is_running() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null) || return 1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

do_start() {
    if is_running; then
        echo "已在运行 (PID $(cat "$PID_FILE"))，无需启动"
        return 0
    fi
    # 清理过期 pid 文件
    rm -f "$PID_FILE"

    # 环境准备：git pull + 依赖检查（缺则自动装）
    do_git_pull
    resolve_python || return 1
    mkdir -p assets

    log "使用解释器：$PYTHON"
    echo "启动服务，端口 ${PORT}，日志 $LOG_FILE ..."
    nohup "$PYTHON" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 等待端口就绪（进程存活 + 端口可连 + 监听者确实是本进程，最多 20 秒）
    local i=0 ready=0
    while [ $i -lt 20 ]; do
        kill -0 "$pid" 2>/dev/null || break
        if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
            # 端口通了，但可能是别的进程占着：用 ss 确认监听者是我们（ss 不可用时信任连通性）
            if command -v ss >/dev/null 2>&1; then
                local owner
                owner=$(ss -tlnp 2>/dev/null | grep ":$PORT " | head -1)
                if echo "$owner" | grep -q "pid=$pid,"; then ready=1; break; fi
                [ -n "$owner" ] && break   # 监听者是其他进程，快速失败
            else
                ready=1; break
            fi
        fi
        sleep 1
        i=$((i+1))
    done
    if [ "$ready" = "1" ]; then
        echo "启动成功 (PID $pid)"
        echo "地址: http://0.0.0.0:$PORT"
        return 0
    fi
    echo "启动失败（进程退出或端口 $PORT 被其他进程占用），请查看日志: tail -50 $LOG_FILE"
    kill "$pid" 2>/dev/null
    rm -f "$PID_FILE"
    return 1
}

do_stop() {
    if ! is_running; then
        echo "服务未在运行"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid
    pid=$(cat "$PID_FILE")
    echo "停止服务 (PID $pid) ..."
    kill "$pid" 2>/dev/null

    # 最多等 10 秒优雅退出，否则强杀
    local i=0
    while kill -0 "$pid" 2>/dev/null && [ $i -lt 10 ]; do
        sleep 1
        i=$((i+1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "优雅退出超时，强制 kill -9"
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi
    rm -f "$PID_FILE"
    echo "已停止"
}

do_status() {
    if is_running; then
        echo "运行中 (PID $(cat "$PID_FILE"))，端口 $PORT"
    else
        echo "未运行"
        return 1
    fi
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; do_start ;;
    status)  do_status ;;
    setup)   do_setup ;;
    *)
        echo "用法: $0 {start|stop|restart|status|setup}"
        exit 1
        ;;
esac
