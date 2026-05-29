#!/bin/bash
# =============================================================================
# 航空排故智能问答系统 — Ubuntu 从零部署脚本
#
# 用法:
#   sudo ./deploy.sh                     # 完整部署
#   sudo ./deploy.sh --skip-ollama       # 跳过 Ollama 安装（已安装时）
#   sudo ./deploy.sh --skip-redis        # 跳过 Redis 安装
#   sudo ./deploy.sh --skip-model        # 跳过 LLM 模型下载（离线环境）
#   sudo ./deploy.sh --skip-embedding    # 跳过 Embedding 模型下载
# =============================================================================

set -e

# ─── 解析参数 ────────────────────────────────────────────────────────────────
SKIP_OLLAMA=false
SKIP_REDIS=false
SKIP_MODEL=false
SKIP_EMBEDDING=false

for arg in "$@"; do
    case "$arg" in
        --skip-ollama)   SKIP_OLLAMA=true ;;
        --skip-redis)    SKIP_REDIS=true ;;
        --skip-model)    SKIP_MODEL=true ;;
        --skip-embedding) SKIP_EMBEDDING=true ;;
        --help|-h)
            echo "用法: sudo ./deploy.sh [--skip-ollama] [--skip-redis] [--skip-model] [--skip-embedding]"
            exit 0 ;;
        *)
            echo "未知参数: $arg"
            echo "用法: sudo ./deploy.sh [--skip-ollama] [--skip-redis] [--skip-model] [--skip-embedding]"
            exit 1 ;;
    esac
done

# ─── 常量 ────────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
WEB_DIR="$PROJECT_DIR/web"
MODEL_DIR="$PROJECT_DIR/models/local_models/bge-small-zh-v1.5"
ENV_FILE="$PROJECT_DIR/.env"
NODE_MAJOR=20
LLM_MODEL="qwen3:14b"

# ─── 颜色 ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step_n=0
step()  { step_n=$((step_n + 1)); echo -e "\n${BOLD}[${step_n}] $1${NC}"; }
info()  { echo -e "  ${CYAN}*${NC} $1"; }
ok()    { echo -e "  ${GREEN}OK${NC} $1"; }
warn()  { echo -e "  ${YELLOW}!!${NC} $1"; }
fail()  { echo -e "  ${RED}FAIL${NC} $1"; exit 1; }

# ─── 前置检查 ────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  航空排故智能问答系统 — Ubuntu 部署${NC}"
echo -e "${BOLD}============================================${NC}"

if [ "$(id -u)" -ne 0 ]; then
    fail "请使用 sudo 运行此脚本"
fi

if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null && ! grep -qi "debian" /etc/os-release 2>/dev/null; then
    warn "此脚本针对 Ubuntu/Debian 设计，在其他系统上可能无法正常工作"
fi

ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "aarch64" ]; then
    fail "不支持的架构: $ARCH（仅支持 x86_64 / aarch64）"
fi
ok "系统架构: $ARCH"

TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
info "系统内存: ${TOTAL_MEM_GB}GB"
if [ "$TOTAL_MEM_GB" -lt 8 ]; then
    warn "推荐至少 8GB 内存（当前 ${TOTAL_MEM_GB}GB），qwen3:14b 模型需要较多内存"
fi

DISK_AVAIL_KB=$(df "$PROJECT_DIR" | tail -1 | awk '{print $4}')
DISK_AVAIL_GB=$((DISK_AVAIL_KB / 1024 / 1024))
info "可用磁盘: ${DISK_AVAIL_GB}GB"
if [ "$DISK_AVAIL_GB" -lt 15 ]; then
    warn "推荐至少 15GB 可用空间（模型 + 依赖约需 12GB）"
fi

# ─── 1. 系统依赖 ─────────────────────────────────────────────────────────────

step "更新系统并安装基础依赖"

apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    curl wget git build-essential \
    lsof procps \
    > /dev/null 2>&1

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PYTHON_VERSION"

if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    ok "Python 版本 >= 3.10"
else
    fail "Python 版本过低 ($PYTHON_VERSION)，需要 3.10+"
fi

# ─── 2. Node.js ─────────────────────────────────────────────────────────────

step "安装 Node.js $NODE_MAJOR.x"

if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    ok "Node.js 已安装: $NODE_VER"
else
    info "添加 NodeSource 源..."
    apt-get install -y -qq ca-certificates gnupg > /dev/null 2>&1
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg > /dev/null 2>&1
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -qq
    apt-get install -y -qq nodejs > /dev/null 2>&1
    ok "Node.js $(node --version) 安装完成"
fi

# ─── 3. Ollama ──────────────────────────────────────────────────────────────

step "安装 Ollama 并下载模型"

if [ "$SKIP_OLLAMA" = true ]; then
    warn "跳过 Ollama 安装（--skip-ollama）"
else
    if command -v ollama &>/dev/null; then
        ok "Ollama 已安装: $(ollama --version 2>/dev/null || echo '已存在')"
    else
        info "安装 Ollama（官方脚本）..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama 安装完成"
    fi

    info "启动 Ollama 服务..."
    if ! pgrep -x ollama > /dev/null; then
        ollama serve > /dev/null 2>&1 &
        OLLAMA_PID=$!
        sleep 3
        if ! pgrep -x ollama > /dev/null; then
            fail "Ollama 服务启动失败"
        fi
    fi
    ok "Ollama 服务已运行"

    if [ "$SKIP_MODEL" = true ]; then
        warn "跳过 LLM 模型下载（--skip-model）"
    else
        if ollama list 2>/dev/null | grep -q "$LLM_MODEL"; then
            ok "模型 $LLM_MODEL 已存在"
        else
            info "下载 LLM 模型 $LLM_MODEL（约 9GB，需要较长时间）..."
            ollama pull "$LLM_MODEL"
            ok "模型 $LLM_MODEL 下载完成"
        fi
    fi
fi

# ─── 4. Redis (可选) ────────────────────────────────────────────────────────

step "安装 Redis"

if [ "$SKIP_REDIS" = true ]; then
    warn "跳过 Redis 安装（--skip-redis），将使用 SQLite 降级方案"
else
    if command -v redis-server &>/dev/null || command -v redis-cli &>/dev/null; then
        ok "Redis 已安装"
    else
        apt-get install -y -qq redis-server > /dev/null 2>&1
        ok "Redis 安装完成"
    fi

    if ! systemctl is-active --quiet redis-server 2>/dev/null; then
        systemctl start redis-server 2>/dev/null || redis-server --daemonize yes 2>/dev/null || true
    fi

    if redis-cli ping > /dev/null 2>&1; then
        ok "Redis 服务已运行"
    else
        warn "Redis 未运行，将使用 SQLite 降级方案"
    fi
fi

# ─── 5. uv + Python 依赖 ───────────────────────────────────────────────────

step "安装 uv 并配置 Python 环境"

if command -v uv &>/dev/null; then
    ok "uv 已安装: $(uv --version)"
else
    info "安装 uv（Python 包管理器）..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    ok "uv $(uv --version) 安装完成"
fi

cd "$PROJECT_DIR"

info "安装 Python 依赖..."
uv sync
ok "Python 依赖安装完成"

# ─── 6. Embedding 模型 ─────────────────────────────────────────────────────

step "下载 Embedding 模型"

if [ "$SKIP_EMBEDDING" = true ]; then
    warn "跳过 Embedding 模型下载（--skip-embedding）"
else
    if [ -f "$MODEL_DIR/model.safetensors" ] || [ -f "$MODEL_DIR/pytorch_model.bin" ]; then
        ok "Embedding 模型已存在: $MODEL_DIR"
    else
        info "下载 bge-small-zh-v1.5（约 91MB）..."
        mkdir -p "$MODEL_DIR"
        uv run python -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
model.save('$MODEL_DIR')
print('模型下载完成')
"
        ok "Embedding 模型已下载到 $MODEL_DIR"
    fi
fi

# ─── 7. 环境配置 ────────────────────────────────────────────────────────────

step "生成 .env 配置"

if [ -f "$ENV_FILE" ]; then
    ok ".env 文件已存在，跳过"
else
    cat > "$ENV_FILE" << 'ENVEOF'
# LLM Configuration (Local Ollama)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
ENVEOF
    ok ".env 文件已创建"
fi

# ─── 8. 前端依赖 ────────────────────────────────────────────────────────────

step "安装前端依赖"

if [ -d "$WEB_DIR/node_modules" ]; then
    ok "前端依赖已存在，跳过"
else
    cd "$WEB_DIR"
    npm install --silent 2>/dev/null
    cd "$PROJECT_DIR"
    ok "前端依赖安装完成"
fi

# ─── 9. 创建必要目录 ────────────────────────────────────────────────────────

step "创建运行时目录"

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs" "$PROJECT_DIR/.pids"
ok "目录就绪: data/, logs/, .pids/"

# ─── 10. 验证 ───────────────────────────────────────────────────────────────

step "验证部署"

ERRORS=0

if command -v python3 &>/dev/null; then
    ok "Python $(python3 --version)"
else
    warn "Python 未找到"; ERRORS=$((ERRORS + 1))
fi

if command -v node &>/dev/null; then
    ok "Node.js $(node --version)"
else
    warn "Node.js 未找到"; ERRORS=$((ERRORS + 1))
fi

if [ "$SKIP_OLLAMA" = false ]; then
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        ok "Ollama 服务正常"
    else
        warn "Ollama 服务未响应（可能需要手动启动: ollama serve）"
    fi
fi

if [ "$SKIP_REDIS" = false ]; then
    if redis-cli ping > /dev/null 2>&1; then
        ok "Redis 服务正常"
    else
        warn "Redis 未运行（将使用 SQLite 降级）"
    fi
fi

if [ -f "$ENV_FILE" ]; then
    ok ".env 配置就绪"
else
    warn ".env 文件不存在"; ERRORS=$((ERRORS + 1))
fi

if [ "$SKIP_EMBEDDING" = false ]; then
    if [ -f "$MODEL_DIR/model.safetensors" ] || [ -f "$MODEL_DIR/pytorch_model.bin" ]; then
        ok "Embedding 模型就绪"
    else
        warn "Embedding 模型未找到"; ERRORS=$((ERRORS + 1))
    fi
fi

# ─── 部署摘要 ────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}============================================${NC}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "  ${GREEN}部署完成！所有组件就绪${NC}"
else
    echo -e "  ${YELLOW}部署完成（$ERRORS 项警告）${NC}"
fi
echo -e "${BOLD}============================================${NC}"
echo ""
echo "  下一步操作:"
echo ""
echo "    1. 启动服务:"
echo "       ./run.sh"
echo ""
echo "    2. 访问地址:"
echo "       前端:  http://localhost:3000"
echo "       后端:  http://localhost:8000"
echo "       文档:  http://localhost:8000/docs"
echo ""
echo "    3. 导入文档:"
echo "       curl -X POST http://localhost:8000/documents/upload \\"
echo "         -F 'file=@your_document.md'"
echo ""
echo "    4. 停止服务:"
echo "       ./stop.sh"
echo ""
