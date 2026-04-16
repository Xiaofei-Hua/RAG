#!/bin/bash
# =============================================================================
# 航空排故智能问答系统 — 一键停止
# =============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$PROJECT_DIR/.pids"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  航空排故智能问答系统 — 停止中${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

STOPPED=0

# ─── Stop frontend ──────────────────────────────────────────────────────────

if [ -f "$PID_DIR/frontend.pid" ]; then
    PID=$(cat "$PID_DIR/frontend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        # Wait up to 5 seconds for graceful shutdown
        for i in $(seq 1 5); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        # Force kill if still alive
        kill -9 "$PID" 2>/dev/null
        ok "前端已停止 (PID: $PID)"
        STOPPED=$((STOPPED + 1))
    else
        warn "前端进程已不存在 (PID: $PID)"
    fi
    rm -f "$PID_DIR/frontend.pid"
else
    warn "前端未在运行"
fi

# ─── Stop backend ───────────────────────────────────────────────────────────

if [ -f "$PID_DIR/backend.pid" ]; then
    PID=$(cat "$PID_DIR/backend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        for i in $(seq 1 5); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$PID" 2>/dev/null
        ok "后端已停止 (PID: $PID)"
        STOPPED=$((STOPPED + 1))
    else
        warn "后端进程已不存在 (PID: $PID)"
    fi
    rm -f "$PID_DIR/backend.pid"
else
    warn "后端未在运行"
fi

# ─── Cleanup orphan processes on the ports ──────────────────────────────────

for PORT in 8000 3000; do
    PIDS=$(lsof -ti:$PORT 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill 2>/dev/null
        ok "清理端口 $PORT 上的残留进程"
        STOPPED=$((STOPPED + 1))
    fi
done

# ─── Summary ────────────────────────────────────────────────────────────────

echo ""
if [ $STOPPED -gt 0 ]; then
    echo -e "  ${GREEN}所有服务已停止${NC}"
else
    echo "  没有正在运行的服务"
fi
echo ""
