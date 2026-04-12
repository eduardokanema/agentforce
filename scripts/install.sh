#!/bin/bash
# Install AgentForce — curl-based installer
# Usage: curl -fsSL https://raw.githubusercontent.com/eduardokanema/agentforce/main/scripts/install.sh | bash

set -euo pipefail

GITHUB_REPO="https://github.com/eduardokanema/agentforce"
BRANCH="main"
VERSION="2.0.0"
PYTHON_BIN=""
TMP_DIR=""
SOURCE_DIR=""
MISSION_BIN=""
UI_TOOL="${AGENTFORCE_INSTALL_UI_TOOL:-auto}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()    { echo -e "${GREEN}[agentforce]${NC} $1"; }
warn()   { echo -e "${YELLOW}[agentforce]${NC} $1"; }
fail()   { echo -e "${RED}[agentforce]${NC} $1" >&2; exit 1; }

cleanup() {
    if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}

trap cleanup EXIT

find_python() {
    local candidates=(
        python3.13
        python3.12
        python3.11
        python3
    )
    local candidate ver
    for candidate in "${candidates[@]}"; do
        if ! command -v "$candidate" >/dev/null 2>&1; then
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
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        fail "pip is required but not installed"
    fi
    log "pip OK"
}

python_script_dirs() {
    "$PYTHON_BIN" - <<'PY'
import os
import site
import sysconfig

paths = []
for value in (sysconfig.get_path("scripts"), os.path.join(site.getuserbase(), "bin")):
    if value and value not in paths:
        paths.append(value)
for path in paths:
    print(path)
PY
}

add_python_script_dirs_to_path() {
    while IFS= read -r path; do
        if [[ -n "$path" && ":$PATH:" != *":$path:"* ]]; then
            PATH="$path:$PATH"
        fi
    done < <(python_script_dirs)
    export PATH
}

download_source_tree() {
    if [[ -n "${AGENTFORCE_INSTALL_SOURCE_DIR:-}" ]]; then
        SOURCE_DIR="$(cd "${AGENTFORCE_INSTALL_SOURCE_DIR}" && pwd -P)"
        [[ -d "${SOURCE_DIR}" ]] || fail "AGENTFORCE_INSTALL_SOURCE_DIR does not exist: ${AGENTFORCE_INSTALL_SOURCE_DIR}"
        log "Using local source tree at ${SOURCE_DIR}"
    else
        TMP_DIR=$(mktemp -d)
        local archive_url="${GITHUB_REPO}/archive/refs/heads/${BRANCH}.tar.gz"
        local archive_path="${TMP_DIR}/agentforce.tar.gz"

        log "Downloading AgentForce source archive..."
        curl -fsSL "${archive_url}" -o "${archive_path}" || fail "Failed to download ${archive_url}"
        tar -xzf "${archive_path}" -C "${TMP_DIR}" || fail "Failed to extract source archive"

        SOURCE_DIR=$(find "${TMP_DIR}" -mindepth 1 -maxdepth 1 -type d -name "agentforce-*" | head -n 1)
        [[ -n "${SOURCE_DIR}" && -d "${SOURCE_DIR}" ]] || fail "Could not locate extracted AgentForce source tree"
    fi

    [[ -f "${SOURCE_DIR}/ui/package.json" ]] || fail "Downloaded source is missing ui/package.json"
    [[ -f "${SOURCE_DIR}/scripts/smoke_test.sh" ]] || fail "Downloaded source is missing scripts/smoke_test.sh"

    log "Source tree ready"
}

resolve_ui_tool() {
    case "${UI_TOOL}" in
        auto)
            if command -v npm >/dev/null 2>&1; then
                echo "npm"
                return 0
            fi
            if command -v bun >/dev/null 2>&1; then
                echo "bun"
                return 0
            fi
            ;;
        npm|bun)
            if command -v "${UI_TOOL}" >/dev/null 2>&1; then
                echo "${UI_TOOL}"
                return 0
            fi
            fail "AGENTFORCE_INSTALL_UI_TOOL=${UI_TOOL} was requested, but '${UI_TOOL}' is not installed"
            ;;
        *)
            fail "Unknown AGENTFORCE_INSTALL_UI_TOOL value: ${UI_TOOL} (expected: auto, npm, bun)"
            ;;
    esac
    return 1
}

build_dashboard_assets() {
    if [[ -f "${SOURCE_DIR}/ui/dist/index.html" ]]; then
        log "Using bundled dashboard assets"
        return 0
    fi

    local tool
    tool="$(resolve_ui_tool)" || fail "Downloaded source is missing built dashboard assets and neither npm nor bun is available to build them"

    log "Building dashboard assets with ${tool}..."
    case "${tool}" in
        npm)
            (
                cd "${SOURCE_DIR}/ui"
                if ! npm ci --no-audit --no-fund --loglevel=error >/dev/null; then
                    warn "npm ci failed, falling back to npm install"
                    npm install --no-audit --no-fund --loglevel=error >/dev/null
                fi
                npm run build >/dev/null
            )
            ;;
        bun)
            (
                cd "${SOURCE_DIR}/ui"
                if ! bun install --frozen-lockfile >/dev/null; then
                    warn "bun install --frozen-lockfile failed, falling back to bun install"
                    bun install >/dev/null
                fi
                bun run build >/dev/null
            )
            ;;
    esac

    [[ -f "${SOURCE_DIR}/ui/dist/index.html" ]] || fail "Dashboard build completed without producing ui/dist/index.html"
    log "Dashboard assets ready"
}

install_package() {
    log "Installing package..."

    if ! "$PYTHON_BIN" -m pip install "${SOURCE_DIR}" -q 2>/dev/null \
        && ! "$PYTHON_BIN" -m pip install "${SOURCE_DIR}" --break-system-packages -q 2>/dev/null \
        && ! "$PYTHON_BIN" -m pip install "${SOURCE_DIR}" --user -q 2>/dev/null \
        && ! "$PYTHON_BIN" -m pip install "${SOURCE_DIR}" --root-user-action=ignore -q 2>/dev/null; then
        fail "Installation failed. pip could not install AgentForce from the downloaded source tree."
    fi

    add_python_script_dirs_to_path
    MISSION_BIN=$(command -v mission || true)

    if [[ -z "${MISSION_BIN}" ]]; then
        local script_dirs
        script_dirs=$(python_script_dirs | tr '\n' ' ')
        fail "Installation completed, but the 'mission' command is not on PATH. Add one of these directories to PATH and rerun the installer: ${script_dirs}"
    fi

    log "Installed CLI at ${MISSION_BIN}"
}

verify_install() {
    if [[ -z "${TMP_DIR}" ]]; then
        TMP_DIR=$(mktemp -d)
    fi
    local verify_home="${TMP_DIR}/verify-home"
    mkdir -p "${verify_home}"

    log "Verifying the dashboard quick start..."
    HOME="${verify_home}" \
    AGENTFORCE_SMOKE_COMMAND="${MISSION_BIN}" \
    AGENTFORCE_SMOKE_PYTHON="${PYTHON_BIN}" \
    bash "${SOURCE_DIR}/scripts/smoke_test.sh"
}

print_success() {
    log "Installed successfully!"
    echo
    echo "Quick start:"
    echo "  mission serve --daemon"
    echo "  # If port 8080 is busy:"
    echo "  mission serve --daemon --port 8091"
    echo
    echo "First use:"
    echo "  1. Open the dashboard in your browser"
    echo "  2. Go to Flight Director"
    echo "  3. Describe what you want to build"
    echo "  4. Launch a mission when the draft is ready"
}

echo "╔══════════════════════════════════════╗"
echo "║        AgentForce v${VERSION}           ║"
echo "║   Plan, launch, and supervise AI     ║"
echo "╚══════════════════════════════════════╝"
echo

check_python
check_pip
download_source_tree
build_dashboard_assets
install_package
verify_install
print_success
