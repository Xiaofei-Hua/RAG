#!/bin/bash
# =============================================================================
# RAG offline bundle installer.
#
# Usage:
#   ./install_offline.sh /opt/rag-platform
#
# This script expects to be run from an extracted offline bundle directory. It
# installs the bundled project files, Python wheelhouse, local models, frontend
# build artifacts, and PaddleOCR model cache without network access.
# =============================================================================

set -e

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${1:-/opt/rag-platform}"
PROJECT_SRC="$BUNDLE_DIR/project"
WHEELHOUSE_DIR="$BUNDLE_DIR/wheelhouse"
REQUIREMENTS_FILE="$BUNDLE_DIR/requirements.lock.txt"
PADDLEOCR_SRC="$BUNDLE_DIR/paddleocr/official_models"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "  ${CYAN}*${NC} $1"; }
ok()    { echo -e "  ${GREEN}OK${NC} $1"; }
warn()  { echo -e "  ${YELLOW}!!${NC} $1"; }
fail()  { echo -e "  ${RED}FAIL${NC} $1"; exit 1; }

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  RAG Offline Bundle Installer${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

[ -d "$PROJECT_SRC" ] || fail "Missing bundle project directory: $PROJECT_SRC"
[ -d "$WHEELHOUSE_DIR" ] || fail "Missing wheelhouse directory: $WHEELHOUSE_DIR"
[ -f "$REQUIREMENTS_FILE" ] || fail "Missing requirements file: $REQUIREMENTS_FILE"

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 is required on the target host"
fi

mkdir -p "$TARGET_DIR"
info "Copying project to $TARGET_DIR"
cp -a "$PROJECT_SRC"/. "$TARGET_DIR"/
ok "Project files installed"

mkdir -p "$TARGET_DIR/models/local_models"
if [ -d "$BUNDLE_DIR/models/local_models" ]; then
    info "Restoring local model directory"
    cp -a "$BUNDLE_DIR/models/local_models"/. "$TARGET_DIR/models/local_models"/
    ok "Local models restored"
else
    warn "No bundled models/local_models directory found"
fi

if [ -d "$PADDLEOCR_SRC" ]; then
    info "Restoring PaddleOCR model cache to $HOME/.paddlex/official_models"
    mkdir -p "$HOME/.paddlex"
    rm -rf "$HOME/.paddlex/official_models"
    cp -a "$PADDLEOCR_SRC" "$HOME/.paddlex/official_models"
    ok "PaddleOCR cache restored"
else
    warn "No bundled PaddleOCR cache found; OCR may try to download models on first use"
fi

info "Creating Python virtual environment"
python3 -m venv "$TARGET_DIR/.venv"
"$TARGET_DIR/.venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$TARGET_DIR/.venv/bin/python" -m pip install --no-index --find-links "$WHEELHOUSE_DIR" -r "$REQUIREMENTS_FILE"
ok "Python dependencies installed from local wheelhouse"

if [ -f "$BUNDLE_DIR/env.offline" ]; then
    cp "$BUNDLE_DIR/env.offline" "$TARGET_DIR/.env"
    ok ".env restored from offline bundle"
elif [ ! -f "$TARGET_DIR/.env" ] && [ -f "$TARGET_DIR/.env.example" ]; then
    cp "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
    warn ".env created from .env.example; review model paths before starting"
fi

if command -v ollama >/dev/null 2>&1; then
    cat <<EOF

Ollama is installed on this host. To use bundled Ollama models, start it with:

  export OLLAMA_MODELS="$TARGET_DIR/models/local_models/ollama"
  ollama serve

If systemd manages Ollama, add this environment variable to the service:

  Environment="OLLAMA_MODELS=$TARGET_DIR/models/local_models/ollama"

EOF
else
    warn "Ollama executable is not installed; install Ollama before starting LLM-backed chat"
fi

cat <<EOF
${BOLD}Offline install complete.${NC}

Start the backend:
  cd "$TARGET_DIR"
  .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

Frontend static files are already bundled under web/dist and will be served by FastAPI.
EOF
