#!/bin/bash
# =============================================================================
# 航空排故智能问答系统 — 一键启动
#
# 启动后端 (FastAPI :8000) 和前端 (Vite :3000)
# 访问地址: http://localhost:3000
# =============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$PROJECT_DIR/data"
PID_DIR="$PROJECT_DIR/.pids"
LOG_DIR="$PROJECT_DIR/logs"
VENV_DIR="$PROJECT_DIR/.venv"
WEB_DIR="$PROJECT_DIR/web"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  航空排故智能问答系统 — 启动中${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

# Create directories
mkdir -p "$DATA_DIR" "$PID_DIR" "$LOG_DIR"

# ─── Check if already running ───────────────────────────────────────────────

for svc in backend frontend; do
    if [ -f "$PID_DIR/$svc.pid" ]; then
        OLD_PID=$(cat "$PID_DIR/$svc.pid")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            warn "$svc 已在运行 (PID: $OLD_PID)，先停止..."
            kill "$OLD_PID" 2>/dev/null && sleep 1
            kill -9 "$OLD_PID" 2>/dev/null
        fi
        rm -f "$PID_DIR/$svc.pid"
    fi
done

# ─── Check Python venv ──────────────────────────────────────────────────────

if [ ! -f "$VENV_DIR/bin/python" ]; then
    info "创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
    ok "虚拟环境已创建"
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Install Python dependencies if uvicorn not available
if ! "$PYTHON" -c "import uvicorn" 2>/dev/null; then
    info "安装 Python 依赖（首次运行）..."
    "$PIP" install -q -r "$PROJECT_DIR/requirements.txt"
    ok "Python 依赖安装完成"
fi

# Download embedding model if not present
MODEL_DIR="$PROJECT_DIR/models/local_models/bge-small-zh-v1.5"
if [ ! -f "$MODEL_DIR/model.safetensors" ]; then
    info "下载 Embedding 模型 bge-small-zh-v1.5（约 91MB，仅首次）..."
    mkdir -p "$MODEL_DIR"
    "$PYTHON" -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
model.save('$MODEL_DIR')
print('模型下载完成')
"
    ok "Embedding 模型已下载到本地"
else
    ok "Embedding 模型已就绪"
fi

# ─── Check Node.js ──────────────────────────────────────────────────────────

if ! command -v node &>/dev/null; then
    fail "Node.js 未安装，请先安装: brew install node"
fi
ok "Node.js $(node --version)"

# Install frontend dependencies if needed
if [ ! -d "$WEB_DIR/node_modules" ]; then
    info "安装前端依赖（首次运行）..."
    cd "$WEB_DIR" && npm install --silent 2>/dev/null && cd "$PROJECT_DIR"
    ok "前端依赖安装完成"
fi

# ─── Start Backend ──────────────────────────────────────────────────────────

info "启动后端服务..."

cd "$PROJECT_DIR"
"$PYTHON" -m uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info \
    > "$LOG_DIR/backend.log" 2>&1 &

BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"

# Wait for backend to be ready (max 30s)
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        ok "后端已启动 (PID: $BACKEND_PID, 端口: 8000)"
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo ""
        fail "后端启动失败，日志: $LOG_DIR/backend.log"
    fi
    sleep 1
done

if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    warn "后端仍在初始化，已在后台运行 (PID: $BACKEND_PID)"
fi

# ─── Start Frontend ─────────────────────────────────────────────────────────

info "启动前端服务..."

cd "$WEB_DIR"
npx vite --host 0.0.0.0 --port 3000 \
    > "$LOG_DIR/frontend.log" 2>&1 &

FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$PID_DIR/frontend.pid"
cd "$PROJECT_DIR"

sleep 3
if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    ok "前端已启动 (PID: $FRONTEND_PID, 端口: 3000)"
else
    fail "前端启动失败，日志: $LOG_DIR/frontend.log"
fi

# ─── Summary ────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "  ${GREEN}✓ 所有服务已启动${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo "  前端地址:  http://localhost:3000"
echo "  后端 API:  http://localhost:8000"
echo "  API 文档:  http://localhost:8000/docs"
echo ""
echo "  后端日志:  tail -f $LOG_DIR/backend.log"
echo "  前端日志:  tail -f $LOG_DIR/frontend.log"
echo ""
echo "  停止服务:  ./stop.sh"
echo ""
