"""Point every data directory at a throwaway copy before the app is imported.

`core.paths` reads PROJECTS_PATH / KNOWLEDGE_PATH / LOGS_PATH from the
environment at import time and honours an override only if the directory
already exists. Without this file the suite ran against the real
`backend/knowledge` and `backend/projects`, and `test_memory_system`'s
`memory_system.clear(scope="session")` deleted every real session memory file
on every run. Seed data (channel guides, seed topics, existing projects) is
copied in so tests see the same shape as production, minus agent memory.
"""
import os
import shutil
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_SANDBOX = Path(tempfile.mkdtemp(prefix="buzzcaf-tests-"))


def _copy(src: Path, dst: Path, ignore=None) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
    else:
        dst.mkdir(parents=True, exist_ok=True)


_copy(
    _BACKEND / "knowledge",
    _SANDBOX / "knowledge",
    ignore=shutil.ignore_patterns("*_memory.json", "__pycache__", "*.pyc"),
)
_copy(_BACKEND / "projects", _SANDBOX / "projects", ignore=shutil.ignore_patterns("voice_profiles"))
(_SANDBOX / "logs").mkdir(parents=True, exist_ok=True)

os.environ["KNOWLEDGE_PATH"] = str(_SANDBOX / "knowledge")
os.environ["PROJECTS_PATH"] = str(_SANDBOX / "projects")
os.environ["LOGS_PATH"] = str(_SANDBOX / "logs")

# Guard against a stale override in .env: core.config loads the repo .env with
# override=True, which would silently redirect the suite back to real data.
os.environ.setdefault("BUZZCAF_TEST_SANDBOX", str(_SANDBOX))
os.environ["SENTINEL_PIPE"] = r"\\.\pipe\BuzzcafTestSentinelAbsent"
os.environ.setdefault("APP_ENV", "test")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_SANDBOX, ignore_errors=True)
