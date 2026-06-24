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
#   sudo ./deploy.sh --build-offline-bundle
#                                           # 在线预热后生成离线部署包
# =============================================================================

set -e

# ─── 解析参数 ────────────────────────────────────────────────────────────────
SKIP_OLLAMA=false
SKIP_REDIS=false
SKIP_MODEL=false
SKIP_EMBEDDING=false
SKIP_RERANKER=false
SKIP_OCR=false
BUILD_OFFLINE_BUNDLE=false
OFFLINE_BUNDLE_DIR=""

for arg in "$@"; do
    case "$arg" in
        --skip-ollama)   SKIP_OLLAMA=true ;;
        --skip-redis)    SKIP_REDIS=true ;;
        --skip-model)    SKIP_MODEL=true ;;
        --skip-embedding) SKIP_EMBEDDING=true ;;
        --skip-reranker) SKIP_RERANKER=true ;;
        --skip-ocr)      SKIP_OCR=true ;;
        --build-offline-bundle) BUILD_OFFLINE_BUNDLE=true ;;
        --offline-bundle-dir=*) OFFLINE_BUNDLE_DIR="${arg#*=}" ;;
        --help|-h)
            echo "用法: sudo ./deploy.sh [--skip-ollama] [--skip-redis] [--skip-model] [--skip-embedding] [--skip-reranker] [--skip-ocr] [--build-offline-bundle] [--offline-bundle-dir=DIR]"
            exit 0 ;;
        *)
            echo "未知参数: $arg"
            echo "用法: sudo ./deploy.sh [--skip-ollama] [--skip-redis] [--skip-model] [--skip-embedding] [--skip-reranker] [--skip-ocr] [--build-offline-bundle] [--offline-bundle-dir=DIR]"
            exit 1 ;;
    esac
done

# ─── 常量 ────────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
WEB_DIR="$PROJECT_DIR/web"
ENV_FILE="$PROJECT_DIR/.env"
NODE_MAJOR=20
LOCAL_MODELS_DIR="$PROJECT_DIR/models/local_models"
OLLAMA_MODELS_DIR="${OLLAMA_MODELS:-$LOCAL_MODELS_DIR/ollama}"
OFFLINE_BUNDLE_DIR="${OFFLINE_BUNDLE_DIR:-$PROJECT_DIR/offline_bundle}"
PADDLEOCR_CACHE_DIR="${PADDLEOCR_CACHE_DIR:-$HOME/.paddlex/official_models}"
export OLLAMA_MODELS="$OLLAMA_MODELS_DIR"
if [ -z "${LLM_MODEL:-}" ] && [ -f "$ENV_FILE" ]; then
    LLM_MODEL=$(sed -n 's/^LLM_MODEL=//p' "$ENV_FILE" | tail -1)
fi
LLM_MODEL="${LLM_MODEL:-qwen3:14b}"

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

sanitize_model_name() {
    echo "$1" | sed 's#[/:]#_#g'
}

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

    mkdir -p "$OLLAMA_MODELS_DIR"
    info "配置 Ollama 模型目录: $OLLAMA_MODELS_DIR"
    if systemctl list-unit-files ollama.service >/dev/null 2>&1; then
        OLLAMA_SERVICE_FILE="/etc/systemd/system/ollama.service"
        if [ -f "$OLLAMA_SERVICE_FILE" ]; then
            if grep -q '^Environment="OLLAMA_MODELS=' "$OLLAMA_SERVICE_FILE"; then
                sed -i "s#^Environment=\"OLLAMA_MODELS=.*#Environment=\"OLLAMA_MODELS=$OLLAMA_MODELS_DIR\"#" "$OLLAMA_SERVICE_FILE"
            else
                sed -i "/\[Service\]/a Environment=\"OLLAMA_MODELS=$OLLAMA_MODELS_DIR\"" "$OLLAMA_SERVICE_FILE"
            fi
            systemctl daemon-reload || true
            systemctl restart ollama || true
        fi
    elif pgrep -x ollama > /dev/null; then
        warn "检测到非 systemd Ollama 正在运行；如需离线打包，请确认它使用 OLLAMA_MODELS=$OLLAMA_MODELS_DIR"
    fi

    info "启动 Ollama 服务..."
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        OLLAMA_MODELS="$OLLAMA_MODELS_DIR" ollama serve > /dev/null 2>&1 &
        OLLAMA_PID=$!
        sleep 3
        if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
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
# Install with the ocr extra so the standard offline bundle retains PaddleOCR
# capability. The ocr extra was split out of base deps (F20) so minimal CPU
# deploys can skip it; the bundle deploy keeps OCR by default.
uv sync --extra ocr
ok "Python 依赖安装完成"

# ─── 6. Embedding 模型 ─────────────────────────────────────────────────────

step "下载 Embedding 模型"

if [ "$SKIP_EMBEDDING" = true ]; then
    warn "跳过 Embedding 模型下载（--skip-embedding）"
else
    if uv run python -c "
from models.embedding_models import is_embedding_model_cached
raise SystemExit(0 if is_embedding_model_cached() else 1)
"; then
        ok "配置的 Embedding 模型已存在"
    else
        info "下载配置的 Embedding 模型..."
        uv run python -c "
from sentence_transformers import SentenceTransformer
from pathlib import Path
from utils.env_utils import EMBEDDING_MODEL, EMBEDDING_MODEL_PATH
if not EMBEDDING_MODEL_PATH:
    raise SystemExit('EMBEDDING_MODEL_PATH cannot be empty when deploy.sh downloads a model')
Path(EMBEDDING_MODEL_PATH).mkdir(parents=True, exist_ok=True)
model = SentenceTransformer(EMBEDDING_MODEL)
model.save(EMBEDDING_MODEL_PATH)
print('模型下载完成')
"
        ok "Embedding 模型已下载到配置的本地路径"
    fi
fi

# ─── 7. 环境配置 ────────────────────────────────────────────────────────────

step "生成 .env 配置"

if [ -f "$ENV_FILE" ]; then
    ok ".env 文件已存在，跳过"
else
    cat > "$ENV_FILE" << ENVEOF
# LLM Configuration (Local Ollama)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=$LLM_MODEL
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60
LLM_MAX_RETRIES=1

# Embedding Configuration
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_MODEL_PATH=models/local_models/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
EMBEDDING_DEVICE=cpu
EMBEDDING_NORMALIZE=true
EMBEDDING_BATCH_SIZE=8

# Optional Reranker Configuration
RERANKER_ENABLED=false
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_MODEL_PATH=models/local_models/reranker/bge-reranker-v2-m3
RERANKER_DEVICE=cpu
RERANKER_WARMUP=false
RERANKER_CANDIDATE_TOP_K=10
RERANKER_TOP_K=5
RERANKER_BATCH_SIZE=4

# Optional OpenTelemetry Configuration
OTEL_ENABLED=false
OTEL_SERVICE_NAME=rag-platform
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_SAMPLE_RATE=1.0
OTEL_CONSOLE_EXPORTER=false

# Storage
MILVUS_DB_URI=./milvus_data.db
COLLECTION_NAME=t_collection01

# PDF ingestion and OCR
PDF_EXTRACT_TABLES=true
PDF_OCR_ENABLED=true
PDF_OCR_ENGINE=paddleocr
PDF_OCR_LANG=ch
PDF_OCR_DPI=220
PDF_OCR_MIN_TEXT_CHARS=20
PDF_ASSET_DIR=data/document_assets
PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0
ENVEOF
    ok ".env 文件已创建"
fi

set -a
. "$ENV_FILE"
set +a

# ─── 8. Reranker 模型预热 ──────────────────────────────────────────────────

step "预热 Reranker 模型"

if [ "$SKIP_RERANKER" = true ]; then
    warn "跳过 Reranker 模型预热（--skip-reranker）"
else
    uv run python - <<'PY'
from pathlib import Path

from sentence_transformers import CrossEncoder

from utils.env_utils import PROJECT_ROOT, RERANKER_DEVICE, RERANKER_MODEL, RERANKER_MODEL_PATH


def safe_name(model_name: str) -> str:
    return model_name.replace("/", "_").replace(":", "_")


target = Path(RERANKER_MODEL_PATH) if RERANKER_MODEL_PATH else (
    PROJECT_ROOT / "models" / "local_models" / "reranker" / safe_name(RERANKER_MODEL)
)
target = target.expanduser()
if not target.is_absolute():
    target = PROJECT_ROOT / target

source = str(target) if target.is_dir() else RERANKER_MODEL
print(f"Reranker source: {source}")
model = CrossEncoder(source, device=RERANKER_DEVICE)
target.mkdir(parents=True, exist_ok=True)
model.save(str(target))
print(f"Reranker saved to: {target}")
PY
    ok "Reranker 模型已预热并保存到本地目录"
fi

# ─── 9. OCR 模型预热 ───────────────────────────────────────────────────────

step "预热 OCR 模型"

if [ "$SKIP_OCR" = true ]; then
    warn "跳过 OCR 模型预热（--skip-ocr）"
else
    PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT="${PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT:-0}" uv run python - <<'PY'
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from documents.ocr_engine import extract_text_from_image

probe = Path("/tmp/rag_ocr_prewarm.png")
image = Image.new("RGB", (900, 320), "white")
draw = ImageDraw.Draw(image)
font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
font = ImageFont.truetype(str(font_path), 48) if font_path.exists() else None
draw.text((60, 120), "OCR PREWARM 12345", fill="black", font=font)
image.save(probe)
result = extract_text_from_image(str(probe))
print(f"OCR text: {result.text[:80]!r}")
print(f"OCR confidence: {result.confidence}")
PY
    ok "OCR 模型已预热"
fi

# ─── 10. 前端依赖 ───────────────────────────────────────────────────────────

step "构建前端静态文件"

if [ -d "$WEB_DIR/node_modules" ]; then
    ok "前端依赖已存在，跳过"
else
    cd "$WEB_DIR"
    npm install --silent 2>/dev/null
    cd "$PROJECT_DIR"
    ok "前端依赖安装完成"
fi

cd "$WEB_DIR"
npm run build
cd "$PROJECT_DIR"
ok "前端静态文件已构建，将由 FastAPI 托管"

# ─── 11. 创建必要目录 ───────────────────────────────────────────────────────

step "创建运行时目录"

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs" "$PROJECT_DIR/.pids"
ok "目录就绪: data/, logs/, .pids/"

# ─── 12. 离线部署包 ─────────────────────────────────────────────────────────

if [ "$BUILD_OFFLINE_BUNDLE" = true ]; then
    step "构建离线部署包"

    mkdir -p "$OFFLINE_BUNDLE_DIR"
    BUNDLE_NAME="rag_offline_bundle_$(date +%Y%m%d_%H%M%S)"
    STAGING_DIR="$OFFLINE_BUNDLE_DIR/$BUNDLE_NAME"
    TARBALL="$OFFLINE_BUNDLE_DIR/$BUNDLE_NAME.tar.gz"

    rm -rf "$STAGING_DIR"
    mkdir -p "$STAGING_DIR/project" "$STAGING_DIR/wheelhouse" "$STAGING_DIR/models"

    info "导出 Python 依赖锁定文件"
    uv export --frozen --no-hashes --no-dev --format requirements.txt \
        --output-file "$STAGING_DIR/requirements.lock.txt"

    info "下载 Python wheelhouse（包含 CPU PyTorch 索引）"
    PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://download.pytorch.org/whl/cpu}" \
        "$VENV_DIR/bin/python" -m pip download \
        --prefer-binary \
        --dest "$STAGING_DIR/wheelhouse" \
        -r "$STAGING_DIR/requirements.lock.txt"
    ok "Python wheelhouse 已生成"

    info "复制项目代码与前端构建产物"
    tar -C "$PROJECT_DIR" \
        --exclude='./.git' \
        --exclude='./.venv' \
        --exclude='./offline_bundle' \
        --exclude='./data' \
        --exclude='./logs' \
        --exclude='./.pids' \
        --exclude='./milvus_data.db' \
        --exclude='./models/local_models' \
        --exclude='./web/node_modules' \
        -cf - . | tar -C "$STAGING_DIR/project" -xf -
    ok "项目文件已复制"

    if [ -d "$LOCAL_MODELS_DIR" ]; then
        info "复制本地模型目录: $LOCAL_MODELS_DIR"
        mkdir -p "$STAGING_DIR/models"
        cp -a "$LOCAL_MODELS_DIR" "$STAGING_DIR/models/local_models"
        ok "本地模型目录已复制"
    else
        warn "未找到本地模型目录: $LOCAL_MODELS_DIR"
    fi

    if [ -d "$PADDLEOCR_CACHE_DIR" ]; then
        info "复制 PaddleOCR 模型缓存: $PADDLEOCR_CACHE_DIR"
        mkdir -p "$STAGING_DIR/paddleocr"
        cp -a "$PADDLEOCR_CACHE_DIR" "$STAGING_DIR/paddleocr/official_models"
        ok "PaddleOCR 模型缓存已复制"
    else
        warn "未找到 PaddleOCR 模型缓存: $PADDLEOCR_CACHE_DIR"
    fi

    cp "$PROJECT_DIR/scripts/install_offline.sh" "$STAGING_DIR/install_offline.sh"
    chmod +x "$STAGING_DIR/install_offline.sh"

    info "生成离线 .env"
    RERANKER_BUNDLE_PATH="${RERANKER_MODEL_PATH:-models/local_models/reranker/$(sanitize_model_name "${RERANKER_MODEL:-cross-encoder/ms-marco-MiniLM-L-6-v2}")}"
    cat > "$STAGING_DIR/env.offline" << ENVEOF
# Offline bundle configuration
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=${LLM_MODEL:-qwen3:14b}
LLM_TEMPERATURE=${LLM_TEMPERATURE:-0.0}
LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-4096}
LLM_TIMEOUT=${LLM_TIMEOUT:-60}
LLM_MAX_RETRIES=${LLM_MAX_RETRIES:-1}

EMBEDDING_MODEL=${EMBEDDING_MODEL:-BAAI/bge-small-zh-v1.5}
EMBEDDING_MODEL_PATH=${EMBEDDING_MODEL_PATH:-models/local_models/bge-small-zh-v1.5}
EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION:-512}
EMBEDDING_DEVICE=${EMBEDDING_DEVICE:-cpu}
EMBEDDING_NORMALIZE=${EMBEDDING_NORMALIZE:-true}
EMBEDDING_BATCH_SIZE=${EMBEDDING_BATCH_SIZE:-8}

RERANKER_ENABLED=${RERANKER_ENABLED:-false}
RERANKER_MODEL=${RERANKER_MODEL:-cross-encoder/ms-marco-MiniLM-L-6-v2}
RERANKER_MODEL_PATH=$RERANKER_BUNDLE_PATH
RERANKER_DEVICE=${RERANKER_DEVICE:-cpu}
RERANKER_WARMUP=${RERANKER_WARMUP:-false}
RERANKER_CANDIDATE_TOP_K=${RERANKER_CANDIDATE_TOP_K:-10}
RERANKER_TOP_K=${RERANKER_TOP_K:-5}
RERANKER_BATCH_SIZE=${RERANKER_BATCH_SIZE:-8}

OTEL_ENABLED=false
OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-rag-platform}
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_SAMPLE_RATE=${OTEL_SAMPLE_RATE:-1.0}
OTEL_CONSOLE_EXPORTER=false

MILVUS_DB_URI=./milvus_data.db
COLLECTION_NAME=${COLLECTION_NAME:-t_collection01}

PDF_EXTRACT_TABLES=${PDF_EXTRACT_TABLES:-true}
PDF_OCR_ENABLED=${PDF_OCR_ENABLED:-true}
PDF_OCR_ENGINE=${PDF_OCR_ENGINE:-paddleocr}
PDF_OCR_LANG=${PDF_OCR_LANG:-ch}
PDF_OCR_DPI=${PDF_OCR_DPI:-220}
PDF_OCR_MIN_TEXT_CHARS=${PDF_OCR_MIN_TEXT_CHARS:-20}
PDF_ASSET_DIR=${PDF_ASSET_DIR:-data/document_assets}
PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=${PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT:-0}
ENVEOF

    {
        echo "RAG offline bundle"
        echo "created_at=$(date -Iseconds)"
        echo "project_dir=$PROJECT_DIR"
        echo "llm_model=${LLM_MODEL:-qwen3:14b}"
        echo "ollama_models_dir=$OLLAMA_MODELS_DIR"
        echo "local_models_dir=$LOCAL_MODELS_DIR"
        echo "paddleocr_cache_dir=$PADDLEOCR_CACHE_DIR"
        echo ""
        echo "Bundle size summary:"
        du -sh "$STAGING_DIR"/* 2>/dev/null || true
    } > "$STAGING_DIR/OFFLINE_BUNDLE_MANIFEST.txt"

    info "压缩离线包"
    tar -C "$OFFLINE_BUNDLE_DIR" -czf "$TARBALL" "$BUNDLE_NAME"
    ok "离线部署包已生成: $TARBALL"
fi

# ─── 13. 验证 ───────────────────────────────────────────────────────────────

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
    if uv run python -c "
from models.embedding_models import is_embedding_model_cached
raise SystemExit(0 if is_embedding_model_cached() else 1)
"; then
        ok "Embedding 模型就绪"
    else
        warn "Embedding 模型未找到"; ERRORS=$((ERRORS + 1))
    fi
fi

if [ "$SKIP_RERANKER" = false ]; then
    if uv run python -c "
from core.retrieval.reranker import is_reranker_model_cached
raise SystemExit(0 if is_reranker_model_cached(refresh=True) else 1)
"; then
        ok "Reranker 模型就绪"
    else
        warn "Reranker 模型未找到"; ERRORS=$((ERRORS + 1))
    fi
fi

if [ "$SKIP_OCR" = false ]; then
    if [ -d "$PADDLEOCR_CACHE_DIR" ]; then
        ok "PaddleOCR 模型缓存就绪: $PADDLEOCR_CACHE_DIR"
    else
        warn "PaddleOCR 模型缓存未找到: $PADDLEOCR_CACHE_DIR"; ERRORS=$((ERRORS + 1))
    fi
fi

if [ "$BUILD_OFFLINE_BUNDLE" = true ]; then
    if [ -f "$TARBALL" ]; then
        ok "离线部署包就绪: $TARBALL"
    else
        warn "离线部署包未生成"; ERRORS=$((ERRORS + 1))
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
