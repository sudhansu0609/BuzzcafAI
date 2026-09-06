"""Canonical filesystem locations for the studio backend.

Every path is derived from this file's own location, so the project can be
renamed, copied, or checked out anywhere without editing code. Nothing in the
codebase should hardcode an absolute path -- import from here instead.

Environment variables may override the data directories (PROJECTS_PATH,
KNOWLEDGE_PATH, PROMPTS_PATH, LOGS_PATH). Overrides are honoured only if they
already exist on disk; a stale override silently creating a phantom directory
tree is exactly the failure this module exists to prevent.
"""
import os
from pathlib import Path

# .../backend/core/paths.py -> .../backend
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _resolve(env_key: str, default: Path) -> str:
    """Use an env override only when it points at a directory that exists."""
    override = os.environ.get(env_key)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            return str(candidate)
        # A configured-but-missing path is almost always a leftover from a
        # rename. Fall back to the real location rather than creating it.
        return str(default)
    return str(default)


PROMPTS_DIR = _resolve("PROMPTS_PATH", BACKEND_DIR / "prompts")
KNOWLEDGE_DIR = _resolve("KNOWLEDGE_PATH", BACKEND_DIR / "knowledge")
PROJECTS_DIR = _resolve("PROJECTS_PATH", BACKEND_DIR / "projects")
LOGS_DIR = _resolve("LOGS_PATH", BACKEND_DIR / "logs")

AGENTS_DIR = os.path.join(PROMPTS_DIR, "agents")
WORKFLOWS_DIR = os.path.join(PROMPTS_DIR, "workflows")
ASSETS_DIR = str(BACKEND_DIR / "assets")
CONFIG_DIR = str(BACKEND_DIR / "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DOTENV_PATH = str(BACKEND_DIR / ".env")
ROOT_DOTENV_PATH = str(PROJECT_ROOT / ".env")
