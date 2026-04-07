#!/bin/bash
# Install Agentforce — curl-based installer
# Usage: curl -fsSL https://raw.githubusercontent.com/eduardokanema/agentforce/main/scripts/install.sh | bash

set -e

GITHUB_RAW="https://raw.githubusercontent.com/eduardokanema/agentforce"
INSTALL_DIR="/opt/data/projects/agentforce"
BRANCH="main"
VERSION="2.0.0"
PYTHON_BIN=""

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()    { echo -e "${GREEN}[agentforce]${NC} $1"; }
warn()   { echo -e "${YELLOW}[agentforce]${NC} $1"; }
fail()   { echo -e "${RED}[agentforce]${NC} $1" >&2; exit 1; }

find_python() {
    local candidates=(
        python3.13
        python3.12
        python3.11
        python3
    )
    local candidate ver
    for candidate in "${candidates[@]}"; do
        if ! command -v "$candidate" &>/dev/null; then
            continue
        fi
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        case "$ver" in
            3.11|3.12|3.13|3.14)
                PYTHON_BIN="$candidate"
                return 0
                ;;
        esac
    done
    return 1
}

check_python() {
    if ! find_python; then
        fail "Python 3.11+ required. Tried: python3.13, python3.12, python3.11, python3"
    fi
    local ver
    ver=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log "Using $PYTHON_BIN (Python $ver)"
}

check_pip() {
    if ! "$PYTHON_BIN" -m pip --version &>/dev/null; then
        fail "pip is required but not installed"
    fi
    log "pip OK"
}

install() {
    log "Downloading Agentforce v${VERSION}..."
    
    # Create temp dir
    local tmp
    tmp=$(mktemp -d)
    trap "rm -rf '$tmp'" EXIT

    # Download source files
    log "Downloading source tree..."

    # Create project structure in temp
    mkdir -p "$tmp/agentforce/agentforce/cli"
    mkdir -p "$tmp/agentforce/agentforce/core"
    mkdir -p "$tmp/agentforce/agentforce/memory"
    mkdir -p "$tmp/agentforce/tests/core"
    mkdir -p "$tmp/agentforce/tests/memory"
    mkdir -p "$tmp/agentforce/tests/adapters"
    mkdir -p "$tmp/agentforce/missions"
    mkdir -p "$tmp/agentforce/specs"

    # File list to download
    local files=(
        "agentforce/__init__.py"
        "agentforce/cli/__init__.py"
        "agentforce/cli/cli.py"
        "agentforce/core/__init__.py"
        "agentforce/core/spec.py"
        "agentforce/core/state.py"
        "agentforce/core/engine.py"
        "agentforce/memory/__init__.py"
        "agentforce/memory/memory.py"
        "pyproject.toml"
        "README.md"
        "LICENSE"
    )

    for f in "${files[@]}"; do
        local url="${GITHUB_RAW}/${BRANCH}/${f}"
        if curl -fsSL -o "$tmp/agentforce/$f" "$url" 2>/dev/null; then
            log "  ✓ $f"
        else
            warn "  ✗ $f (optional)"
        fi
    done

    # Install via pip
    log "Installing package..."
    "$PYTHON_BIN" -m pip install "$tmp/agentforce" --break-system-packages -q 2>/dev/null \
        || "$PYTHON_BIN" -m pip install "$tmp/agentforce" -q 2>/dev/null \
        || "$PYTHON_BIN" -m pip install "$tmp/agentforce" --root-user-action=ignore -q 2>/dev/null

    # Verify
    if command -v mission &>/dev/null; then
        log "Installed successfully!"
        log ""
        echo "  Usage:"
        echo "    mission list                    # List all missions"
        echo "    mission start spec.yaml         # Start a new mission"
        echo "    mission status <id>             # Check mission progress"
        echo "    mission report <id>             # Full report with events"
        echo "    mission resolve <id> <task> 'msg'  # Provide human input"
        echo ""
        echo "  Source: $INSTALL_DIR"
    else
        fail "Installation failed — mission binary not found"
    fi
}

# ── Main ──
echo "╔══════════════════════════════════════╗"
echo "║        Agentforce v${VERSION}           ║"
echo "║  Multi-agent Mission Orchestrator    ║"
echo "╚══════════════════════════════════════╝"
echo

check_python
check_pip
install
