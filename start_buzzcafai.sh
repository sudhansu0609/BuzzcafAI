#!/usr/bin/env bash
# ===================================================
# Buzzcaf Studio - macOS / Linux launcher (the .bat/.vbs equivalent).
#
# One file, like "Buzzcaf Studio.vbs" on Windows: it opens the same native
# window via pywebview and leaves the log in your terminal. First run does
# its own setup (venv + backend deps); afterwards it is instant.
#
#   ./start_buzzcafai.sh            normal mode - serves the built UI
#   ./start_buzzcafai.sh --dev      developer mode - Vite dev server, hot reload
#
# Interpreter: BUZZCAF_PYTHON -> .venv/bin/python -> python3 on PATH.
# Node.js is only needed for --dev or to rebuild the UI; the built bundle is
# committed in backend/app/static, so normal mode runs without Node.
# ===================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
VENV_PY="$APP_DIR/.venv/bin/python"
RUN_ARGS=("$@")
DEV_MODE=false
for arg in "$@"; do [ "$arg" = "--dev" ] && DEV_MODE=true; done

need_node() { command -v npm >/dev/null 2>&1 || { echo "Node.js (npm) not found. Install it first:  brew install node" >&2; exit 1; }; }
install_backend_deps() {
  echo "== First run: creating .venv and installing backend dependencies =="
  python3 -m venv "$APP_DIR/.venv"
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r "$APP_DIR/requirements.txt"
}
build_frontend() {
  need_node
  echo "== Building the frontend (result served from backend/app/static) =="
  if [ ! -d "$APP_DIR/frontend/node_modules" ]; then
    (cd "$APP_DIR/frontend" && npm install)
  fi
  (cd "$APP_DIR/frontend" && npm run build)
}

# ── pick interpreter, set up on first run ────────────────────────────
if [ -z "${BUZZCAF_PYTHON:-}" ] && [ ! -x "$VENV_PY" ]; then
  install_backend_deps
fi
PYTHON_EXE="${BUZZCAF_PYTHON:-$VENV_PY}"
command -v "$PYTHON_EXE" >/dev/null 2>&1 || { echo "Python not found. Install it first:  brew install python3" >&2; exit 1; }

# Dependencies may be missing even with a venv (cloned mid-setup); check once.
if ! "$PYTHON_EXE" -c "import fastapi, pywebview" >/dev/null 2>&1; then
  case "$PYTHON_EXE" in
    *".venv/"*) install_backend_deps ;;
    *) echo "Python dependencies missing for $PYTHON_EXE." >&2
       echo "Create the venv with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
       exit 1 ;;
  esac
fi

if [ "$DEV_MODE" = true ]; then
  need_node
  if [ ! -d "$APP_DIR/frontend/node_modules" ]; then
    echo "== Installing frontend dev dependencies =="
    (cd "$APP_DIR/frontend" && npm install)
  fi
elif [ ! -f "$APP_DIR/backend/app/static/index.html" ]; then
  # No built UI present (shouldn't happen: it is committed). Build if we can.
  build_frontend || { echo "No built UI in backend/app/static and the build failed; see above." >&2; exit 1; }
fi

echo "==================================================="
echo " Buzzcaf Studio"
echo " Interpreter: $PYTHON_EXE"
echo " Log file:    backend/logs/studio.log"
echo "==================================================="

# -X utf8 matches the Windows launcher; PYTHONIOENCODING keeps Hinglish log
# lines from crashing a non-UTF-8 terminal.
export PYTHONIOENCODING=utf-8
exec "$PYTHON_EXE" -X utf8 "$APP_DIR/backend/desktop_app.py" "${RUN_ARGS[@]}"
