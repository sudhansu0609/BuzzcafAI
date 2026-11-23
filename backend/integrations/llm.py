import contextlib
import contextvars
import functools
import math
import os
import json
import threading
import logging
import re
import subprocess
import sys
import time
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


from core.errors import LLMUnavailable
from integrations import idle_offload
from core.paths import CONFIG_PATH

logger = logging.getLogger("buzzcaf_ai.llm")

# One LM Studio request at a time: parallel slots share one KV cache.
_LM_STUDIO_GATE = threading.BoundedSemaphore(1)
# model -> when its slot count was last checked (`_lm_studio_ready`).
_PARALLEL_CHECKED: Dict[str, float] = {}
# The `usage` block of this thread's latest OpenAI-style reply (`_metered`).
_CALL = threading.local()


def _metered(fn):
    """Record every generate call -- which model answered, for which job, its
    tokens and how long it took -- in `integrations.llm_usage`. Never lets the
    record get in the way of the answer."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        _CALL.usage = None
        start, text, ok = time.time(), "", False
        try:
            text = fn(self, *args, **kwargs)
            ok = not self.last_response_simulated
            return text
        finally:
            try:
                from integrations import llm_usage
                usage = getattr(_CALL, "usage", None) or {}
                # (system_prompt, user_prompt | messages, require_json, tier, ...)
                system_prompt = kwargs.get("system_prompt", args[0] if args else "")
                prompt = kwargs.get("user_prompt", kwargs.get("messages", args[1] if len(args) > 1 else ""))
                messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": str(prompt)}]
                tier = kwargs.get("tier", args[3] if len(args) > 3 else None)
                llm_usage.record(
                    provider=self.last_provider if ok else None, model=getattr(self, "last_model", ""),
                    job=_CURRENT_JOB.get(), step=_CURRENT_STEP.get(), tier=tier,
                    prompt_tokens=usage.get("prompt_tokens") or estimate_tokens(system_prompt, messages),
                    completion_tokens=usage.get("completion_tokens") or len(str(text or "")) // 3,
                    cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                    estimated=not usage, seconds=time.time() - start, ok=ok)
            except Exception as exc:  # noqa: BLE001
                logger.debug("usage record skipped: %s", exc)
    return wrapper

# Environments where falling back to canned text is acceptable. Anywhere else,
# an unreachable provider raises instead of fabricating an answer.
_SIMULATION_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


def _simulation_enabled() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() in _SIMULATION_ENVIRONMENTS


# Every provider we know how to reach, in the order we fall back through them.
# Claude is last: its usage allowance is shared with the creator's own Claude Code use,
# so it is asked for by name (a tier or the Director) and is a last resort, not a default.
FALLBACK_ORDER = ["gemini", "openai", "lm_studio", "llamacpp", "ollama", "claude"]
LOCAL_PROVIDERS = {"lm_studio", "ollama", "llamacpp"}
LOCAL_FALLBACK_ORDER = ["lm_studio", "llamacpp", "ollama"]
DEFAULT_TEMPERATURE = 0.7

# "claude" is the claude-local-api proxy (../claudeAPI): an OpenAI-compatible
# server on this machine that answers through the user's own Claude Code login
# (and falls over to Codex/ChatGPT by itself). It listens on loopback, but the
# prompt still leaves the PC, so Strict Local Mode never picks it as a silent
# fallback -- it runs only when the user named it (selected provider, a tier,
# or `LLMService(forced_provider="claude")`, which produce_video uses when
# Settings -> "Use Claude for video production" is on).
CLAUDE_DEFAULT_URL = "http://127.0.0.1:8787/v1"
CLAUDE_DEFAULT_MODEL = "sonnet"
# Answers from the proxy are fast, but a cold Claude Code worker plus a long
# planning prompt can take a while on the first call.
CLAUDE_TIMEOUT_SECONDS = 240

# "gemini" can talk to a local harness server (http://127.0.0.1:8001) that answers
# through the user's logged-in personal Google OAuth credentials in their OS keyring
# (zero API keys required), or to the official Google Gemini API when an API key is set.
GEMINI_DEFAULT_URL = "http://127.0.0.1:8001"
GEMINI_RETRY_WAIT_S = 20
GEMINI_DEFAULT_MODEL = "flash"
GEMINI_EFFORT_LEVELS = ("low", "medium", "high", "max")
GEMINI_DEFAULT_EFFORT = "high"
GEMINI_TIMEOUT_SECONDS = 120

# Console programs (the `lms` CLI, PowerShell) spawned from the desktop app
# would otherwise each flash a black cmd window on Windows mid-render.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# What we tell Sentinel an LM Studio request may cost when the model name says
# nothing useful. LM Studio's own default (an 8B at a 4-bit quant) lands here.
LM_STUDIO_DEFAULT_MIB = 6144


def estimate_model_mib(name: str) -> int:
    """A rough VRAM figure for a model id like `meta-llama-3-8b-instruct`.

    The Studio never loads a model itself, so it cannot measure one; all it has
    is the id in Settings. Parameter count is the only part of that id that
    reliably means anything, and at the 4-bit quants LM Studio ships by default
    ~0.6 GiB per billion parameters plus a GiB of context and runtime overhead
    is close enough for an admission decision. When the id says nothing, the
    default above is used rather than a number that pretends to knowledge.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*b\b", (name or "").lower())
    if not match:
        return LM_STUDIO_DEFAULT_MIB
    try:
        billions = float(match.group(1))
    except ValueError:
        return LM_STUDIO_DEFAULT_MIB
    if billions <= 0 or billions > 1000:
        return LM_STUDIO_DEFAULT_MIB
    return max(1024, int(billions * 640) + 1024)


# Two tiers, so cheap work (tags, titles, checklists) can go to the local model
# and the writing stays on the strong one (roadmap v9, F1). An empty provider
# means "use the globally selected one". Defaults to local on-device models.
#
# A third tier, "premium" (2026-10-16), is for the few personas whose quality
# decides the video -- the researcher, the script writer, the Shorts writer
# and the SEO manager. It defaults to Claude Opus through the local proxy
# (the creator's call: "the script writer and the researcher must be very
# good ... with Opus"); when the proxy is down or has no key the call falls
# through to the selected provider like any other tier. Settings -> Model
# tiers changes it (an empty provider = the selected one).
#
# 2026-10-27 the creator: "all the scripts, every other agent works on Gemma
# 12B, even in the day; keep the Claude functionality but put Gemma as
# default" -- premium now starts on the selected provider (LM Studio's Gemma)
# too; Claude stays one click away per tier and as every job route's fallback.
DEFAULT_TIERS = {
    "fast": {"provider": "llamacpp", "model": ""},
    "strong": {"provider": "", "model": ""},
    "premium": {"provider": "", "model": ""},
}
MODEL_TIERS = tuple(DEFAULT_TIERS)

# Per-job model routing (2026-10-26): on the Model Routing window the creator
# picks, per kind of work, which model does it -- Claude, Gemma (LM Studio),
# Ollama or Gemini -- and what to fall back to. A job with no provider ("auto")
# keeps the persona's tier as before. The workflow engine names each step's job
# from its output asset (`job_for_asset`); the strategist loop and the chats
# name theirs with `llm_job(...)`. Stored in config `job_routes`.
LLM_JOBS = {
    "research": "Research",
    "script": "Script writing",
    "rewrite": "Rewrites & polish",
    "shorts": "Shorts scripts",
    "seo": "SEO & titles",
    "planning": "Visual & production plans",
    "strategist": "Nightly planner & Director",
    "assistant": "Studio Assistant chat",
}
_ASSET_JOBS = {
    "research": "research",
    "script": "script", "screenplay": "script", "story": "script", "outline": "script", "vlog_plan": "script",
    "script_final": "rewrite", "narration_optimized": "rewrite",
    "shorts_set": "shorts",
    "seo_package": "seo", "publish_details": "seo",
    "visual_plan": "planning", "sound_plan": "planning", "scene_breakdown": "planning",
    "shot_list": "planning", "clip_plan": "planning", "image_plan": "planning",
    "character_plan": "planning", "thumbnail_plan": "planning", "edit_plan": "planning",
}
ROUTE_PROVIDERS = ("", "claude", "lm_studio", "ollama", "gemini")
# Jobs that use Claude only when their route names it as the provider -- never as a
# fallback (config `claude_manual_only_jobs` replaces the list).
CLAUDE_MANUAL_ONLY_JOBS = ("research", "script", "rewrite", "shorts", "seo", "planning")
_CURRENT_JOB: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("llm_job", default=None)
# "workflow/step name" of the workflow step making the calls, for the usage record.
_CURRENT_STEP: "contextvars.ContextVar[str]" = contextvars.ContextVar("llm_step", default="")


@contextlib.contextmanager
def llm_job(job: Optional[str], step: str = ""):
    """Calls made inside this block (in this thread) follow `job`'s route;
    `step` labels them in the usage record (the forecasts read it back)."""
    token = _CURRENT_JOB.set(job if job in LLM_JOBS else None)
    step_token = _CURRENT_STEP.set(step or _CURRENT_STEP.get())
    try:
        yield
    finally:
        _CURRENT_STEP.reset(step_token)
        _CURRENT_JOB.reset(token)


def current_job() -> Optional[str]:
    return _CURRENT_JOB.get()


def job_for_asset(asset_type: Optional[str]) -> Optional[str]:
    return _ASSET_JOBS.get((asset_type or "").strip().lower())


# Day and Night routes (2026-10-26, the creator: "make Gemma write scripts at
# night, by day Claude is ok, a bit slow is fine"). `job_routes_night` holds the
# night ones (a job missing there keeps its day route); they apply inside the
# night hours (`night_hours`, 22:00-09:00 by default) and always in the nightly
# run's own process (nightly_run.py sets BUZZCAF_ROUTE_PROFILE=night).
ROUTE_PROFILES = ("day", "night")
DEFAULT_NIGHT_HOURS = {"start": "22:00", "end": "09:00"}
_PROFILE: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("llm_route_profile", default=None)


def night_hours(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    saved = (config if config is not None else load_config()).get("night_hours") or {}
    return {k: str(saved.get(k) or DEFAULT_NIGHT_HOURS[k]) for k in ("start", "end")}


def route_profile(config: Optional[Dict[str, Any]] = None) -> str:
    """"night" or "day": forced (the nightly run, `route_profile_as`), else by the clock."""
    forced = (_PROFILE.get() or os.environ.get("BUZZCAF_ROUTE_PROFILE", "")).strip().lower()
    if forced in ROUTE_PROFILES:
        return forced
    cfg = config if config is not None else load_config()
    if not cfg.get("job_routes_night"):
        return "day"
    hours, now = night_hours(cfg), datetime.now().strftime("%H:%M")
    start, end = hours["start"], hours["end"]
    inside = (start <= now < end) if start < end else (now >= start or now < end)
    return "night" if inside else "day"


@contextlib.contextmanager
def route_profile_as(profile: str):
    """Calls (and forecasts) inside this block use the `profile` routes."""
    token = _PROFILE.set(profile if profile in ROUTE_PROFILES else None)
    try:
        yield
    finally:
        _PROFILE.reset(token)


def job_routes(config: Optional[Dict[str, Any]] = None, profile: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Every job's {provider, model, fallback} for `profile` (the current one by
    default), blanks filled in."""
    cfg = config if config is not None else load_config()
    profile = profile or route_profile(cfg)
    day = cfg.get("job_routes") or {}
    night = (cfg.get("job_routes_night") or {}) if profile == "night" else {}
    out = {}
    for job in LLM_JOBS:
        entry = night.get(job) if isinstance(night.get(job), dict) else day.get(job)
        entry = entry if isinstance(entry, dict) else {}
        out[job] = {k: str(entry.get(k) or "").strip() for k in ("provider", "model", "fallback")}
        if entry.get("fallback_model"):
            out[job]["fallback_model"] = str(entry["fallback_model"]).strip()
    return out


def normalize_model_name(name: str) -> str:
    """Normalize model string by removing repo prefix, gguf extension, and non-alphanumeric chars."""
    if not name:
        return ""
    s = name.strip().lower()
    if "/" in s:
        s = s.split("/")[-1]
    s = re.sub(r"[-_.]gguf$", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def models_match(configured: str, candidate: str) -> bool:
    """Fuzzy match between configured model identifier and candidate model identifier."""
    if not configured or not candidate:
        return False
    if configured.strip().lower() == candidate.strip().lower():
        return True
    n_conf = normalize_model_name(configured)
    n_cand = normalize_model_name(candidate)
    if n_conf == n_cand:
        return True
    if len(n_conf) >= 5 and (n_conf in n_cand or n_cand in n_conf):
        return True
    return False


def find_lms_binary() -> Optional[str]:
    """Find the path to the LM Studio CLI binary (lms or lms.exe)."""
    import shutil
    lms_path = shutil.which("lms")
    if lms_path and os.path.exists(lms_path):
        return lms_path
    candidates = [
        os.path.expanduser(r"~/.lmstudio/bin/lms.exe"),
        os.path.expanduser(r"~/.lmstudio/bin/lms"),
        r"C:\Users\singh\.lmstudio\bin\lms.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\LM Studio\lms.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def get_loaded_lm_studio_models(base_url: str = "http://localhost:1234") -> List[str]:
    """Return list of model IDs currently loaded in LM Studio memory."""
    import subprocess
    loaded: List[str] = []

    # 1. Fast check: LM Studio REST API (/api/v0/models takes ~10ms)
    try:
        clean_url = base_url.rstrip("/").replace("/v1", "")
        r = requests.get(f"{clean_url}/api/v0/models", timeout=0.8)
        if r.status_code == 200:
            data = r.json().get("data", [])
            for m in data:
                if m.get("state") == "loaded":
                    mid = m.get("id")
                    if mid and mid not in loaded:
                        loaded.append(mid)
            if loaded:
                return loaded
    except Exception as exc:
        logger.debug("Failed querying /api/v0/models: %s", exc)

    # 2. Fallback check: lms CLI process list (lms ps)
    try:
        bin_path = find_lms_binary()
        if bin_path:
            res = subprocess.run([bin_path, "ps"], capture_output=True, text=True, timeout=2,
                                 creationflags=NO_WINDOW)
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines()[1:]:
                    parts = line.split()
                    if parts and parts[0] != "IDENTIFIER":
                        mid = parts[0]
                        if mid not in loaded:
                            loaded.append(mid)
    except Exception as exc:
        logger.debug("Failed running lms ps: %s", exc)

    return loaded


def exact_model_id(name: Optional[str], ids: List[str]) -> Optional[str]:
    """`name` when it is itself one of `ids` (case-insensitive), else None.

    Fuzzy matching is for configured names that are *not* LM Studio IDs (a
    HuggingFace repo, a .gguf filename). When the name is a real ID it must
    win outright: normalised, "google/gemma-4-12b" is a prefix of
    "gemma4-12b-qat-uncensored-...", so fuzzy matching alone would call a
    different model already loaded."""
    wanted = (name or "").strip().lower()
    return next((i for i in ids if i and i.strip().lower() == wanted), None) if wanted else None


def ollama_resident_models(base_url: str = "http://127.0.0.1:11434") -> List[Dict[str, Any]]:
    """[{name, context_length}] for the models Ollama holds in memory (empty when it is down)."""
    try:
        r = requests.get(f"{base_url}/api/ps", timeout=1.5)
        if r.status_code != 200:
            return []
        return [{"name": str(m.get("name") or m.get("model") or ""),
                 "context_length": int(m.get("context_length") or 0)}
                for m in (r.json().get("models") or [])]
    except Exception:  # noqa: BLE001 - Ollama down is "nothing resident"
        return []


def ollama_copy_of(model_name: str, min_context: int = 16384) -> Optional[str]:
    """The name Ollama serves `model_name` under when it already holds that model with at
    least `min_context` of context. The creator's rule (2026-10-21): one model in memory, and
    a copy already loaded is used rather than loading another."""
    if not model_name:
        return None
    for m in ollama_resident_models():
        if m["context_length"] >= min_context and (
                models_match(model_name, m["name"]) or models_match(m["name"], model_name)):
            return m["name"]
    return None


def unload_ollama_models(base_url: str = "http://127.0.0.1:11434") -> int:
    """Eject every model Ollama holds (keep_alive 0): one model in memory at a time."""
    count = 0
    for m in ollama_resident_models(base_url):
        try:
            requests.post(f"{base_url}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
            count += 1
        except Exception as exc:  # noqa: BLE001 - best effort before a load
            logger.info("Could not unload Ollama model %s (%s)", m["name"], exc)
    return count


def is_model_already_loaded(target_model: Optional[str], loaded_models: List[str]) -> Tuple[bool, Optional[str]]:
    """Determine if target_model is already loaded in memory.
    Returns (True, matched_id) if loaded, or (False, None)."""
    if not loaded_models:
        return False, None
    if not target_model or not target_model.strip() or target_model.lower() in ("auto", "default"):
        return True, loaded_models[0]

    # 1. Exact match
    for mid in loaded_models:
        if target_model.strip().lower() == mid.strip().lower():
            return True, mid

    # 2. Fuzzy / normalized match
    for mid in loaded_models:
        if models_match(target_model, mid) or models_match(mid, target_model):
            return True, mid

    # 3. Substring match on normalized stems
    n_target = normalize_model_name(target_model)
    if len(n_target) >= 4:
        for mid in loaded_models:
            n_mid = normalize_model_name(mid)
            if n_target in n_mid or n_mid in n_target:
                return True, mid

    return False, None


def free_idle_comfyui(base_url: str = "http://127.0.0.1:8188") -> bool:
    """Ask ComfyUI to drop its cached models (VRAM and RAM) before an LLM loads -- only
    when nothing is queued or running there, so a render is never cut. ComfyUI keeps
    Wan/Z-Image resident after a job (2026-10-23: ~30 GB committed while idle, then
    Gemma loaded on top and the PC ran out of memory). True when it was asked."""
    try:
        q = requests.get(f"{base_url}/queue", timeout=3).json()
        if q.get("queue_running") or q.get("queue_pending"):
            return False
        r = requests.post(f"{base_url}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
        return r.status_code < 400
    except Exception:  # noqa: BLE001 - ComfyUI not running: nothing to free
        return False


def ensure_local_model_loaded(provider: str = "lm_studio", model_name: Optional[str] = None) -> Dict[str, Any]:
    """Ensure that the requested local model is loaded in LM Studio or Ollama.
    If already loaded, returns status immediately without calling load again.
    If not loaded, attempts to bring it up automatically."""
    import subprocess

    idle_offload.mark_used(provider)  # unloaded again once the Studio is idle

    if provider == "lm_studio":
        try:
            base_url = "http://localhost:1234"
            loaded = get_loaded_lm_studio_models(base_url)
            try:
                r = requests.get(f"{base_url}/api/v0/models", timeout=2.0)
                data = r.json().get("data", []) if r.status_code == 200 else []
            except Exception:
                data = []
            exact = exact_model_id(model_name, [m.get("id", "") for m in data])
            if exact and exact in loaded:
                return {"loaded": True, "model": exact, "already_loaded": True, "all_loaded": loaded,
                        "message": f"Model '{exact}' is already loaded in memory"}

            # If target model (or any model if none specified) is already loaded, NEVER reload it!
            already_loaded, matched_mid = (False, None) if exact else is_model_already_loaded(model_name, loaded)
            if already_loaded and matched_mid:
                logger.info(
                    "LM Studio model '%s' (requested: '%s') is ALREADY loaded. Skipping reload.",
                    matched_mid, model_name or "active",
                )
                return {
                    "loaded": True,
                    "model": matched_mid,
                    "already_loaded": True,
                    "all_loaded": loaded,
                    "message": f"Model '{matched_mid}' is already loaded in memory",
                }

            # If target model is truly not loaded, find matching candidate
            lms_bin = find_lms_binary()
            if not lms_bin:
                return {
                    "loaded": False,
                    "model": model_name or "",
                    "already_loaded": False,
                    "all_loaded": loaded,
                    "message": "lms binary not found to load model",
                }

            target_key = exact
            if model_name and not target_key:
                for m in data:
                    mid = m.get("id", "")
                    if models_match(model_name, mid) or models_match(mid, model_name):
                        target_key = mid
                        break

            # Re-check: Is resolved target_key already loaded?
            if target_key and not exact:
                is_target_loaded, loaded_id = is_model_already_loaded(target_key, loaded)
                if is_target_loaded and loaded_id:
                    logger.info("Resolved model '%s' is already loaded. Skipping reload.", loaded_id)
                    return {
                        "loaded": True,
                        "model": loaded_id,
                        "already_loaded": True,
                        "all_loaded": loaded,
                        "message": f"Model '{loaded_id}' is already loaded",
                    }

            # If no target specified or model not found, and some model is already loaded, DO NOT load arbitrary model
            if not target_key and loaded:
                logger.info("Existing model '%s' is already loaded. Skipping reload.", loaded[0])
                return {
                    "loaded": True,
                    "model": loaded[0],
                    "already_loaded": True,
                    "all_loaded": loaded,
                    "message": f"Active model '{loaded[0]}' is already loaded",
                }

            if not target_key and data and not loaded:
                target_key = data[0].get("id")

            if target_key and target_key not in loaded:
                # One resident LLM on a 16 GB card: a second model beside the
                # first leaves no room for its KV cache (or for ComfyUI).
                for other in loaded:
                    logger.info("Unloading LM Studio model '%s' to make room for '%s'.", other, target_key)
                    subprocess.run([lms_bin, "unload", other], capture_output=True, text=True, timeout=60,
                                   creationflags=NO_WINDOW)
                ejected = unload_ollama_models()
                if ejected:
                    logger.info("Unloaded %d Ollama model(s) before loading '%s' into LM Studio.", ejected, target_key)
                if free_idle_comfyui():
                    logger.info("Freed ComfyUI's cached models before loading '%s' into LM Studio.", target_key)
                logger.info("Attempting to auto-load LM Studio model '%s' via lms CLI...", target_key)
                # One request slot (`_LM_STUDIO_GATE`): the whole context
                # belongs to a single prompt; it grows to fit when needed.
                ctx = int(load_config().get("lm_studio_context_length") or 65536)
                cmd = [lms_bin, "load", target_key, "-c", str(ctx), "--parallel", "1", "-y"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
                if proc.returncode == 0:
                    logger.info("Successfully loaded LM Studio model '%s'", target_key)
                    return {"loaded": True, "model": target_key, "already_loaded": False, "message": f"Successfully loaded {target_key}"}
                else:
                    logger.warning("lms load failed: %s", proc.stderr)
        except Exception as exc:
            logger.warning("Failed to check or load model in LM Studio: %s", exc)

    elif provider == "ollama":
        try:
            r = requests.get("http://localhost:11434/api/ps", timeout=1.5)
            if r.status_code == 200:
                running = [m.get("name") or m.get("model") for m in r.json().get("models", [])]
                if model_name and any(models_match(model_name, m) for m in running):
                    return {"loaded": True, "model": model_name, "already_loaded": True, "all_loaded": running, "message": "Model already loaded"}
                if not model_name and running:
                    return {"loaded": True, "model": running[0], "already_loaded": True, "all_loaded": running, "message": "Active model loaded"}
            return {"loaded": True, "model": model_name or "ollama", "already_loaded": True, "message": "Ollama ready"}
        except Exception as exc:
            logger.warning("Ollama check failed: %s", exc)

    return {"loaded": False, "model": model_name or "", "already_loaded": False, "message": "Could not verify model"}


#: LM Studio's answer when a prompt does not fit the context the model was
#: loaded with ("request (21025 tokens) exceeds the available context size").
_CONTEXT_OVERFLOW_RE = re.compile(r"exceeds? the available context size|context (?:length|window|size)", re.IGNORECASE)


def lm_studio_context_length() -> int:
    """The context the Studio loads an LM Studio model with (`lm_studio_context_length`,
    32k by default). LM Studio's own just-in-time load uses its default instead
    (16k for Gemma), which a full script's visual plan does not fit."""
    try:
        return max(4096, int(load_config().get("lm_studio_context_length") or 65536))
    except (TypeError, ValueError):
        return 65536


def lm_studio_loaded_context(model: str, base_url: str = "http://localhost:1234") -> Optional[int]:
    """The context length `model` is loaded with right now, or None when it is
    not loaded (or LM Studio does not say)."""
    try:
        r = requests.get(f"{base_url}/api/v0/models", timeout=2.0)
        for m in (r.json().get("data", []) if r.status_code == 200 else []):
            if m.get("id") == model and m.get("state") == "loaded" and m.get("loaded_context_length"):
                return int(m["loaded_context_length"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read LM Studio's loaded context: %s", exc)
    return None


def lm_studio_loaded_parallel(model: str) -> Optional[int]:
    """How many request slots `model` is loaded with (`lms ps --json`), or None.
    LM Studio splits the loaded context between the slots: a 64k model loaded
    with its default 4 gives each prompt 16k, and long prompts were refused with
    "Context size has been exceeded" although they fit 64k (2026-10-26)."""
    lms_bin = find_lms_binary()
    if not lms_bin:
        return None
    try:
        proc = subprocess.run([lms_bin, "ps", "--json"], capture_output=True, text=True, timeout=20,
                              creationflags=NO_WINDOW)
        for m in json.loads(proc.stdout or "[]"):
            if model in (m.get("identifier"), m.get("modelKey")) and m.get("parallel"):
                return int(m["parallel"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read LM Studio's parallel slots: %s", exc)
    return None


class ContextTooLarge(Exception):
    """The prompt does not fit even the largest context the Studio allows."""


class GeminiRateLimited(Exception):
    """Google's rate limit is on (the harness said so, or the Studio is waiting for the window)."""


def _harness_gate() -> None:
    """No request to the harness while its rate-limit window is open."""
    from integrations import gemini_limit
    rec = gemini_limit.active()
    if rec:
        raise GeminiRateLimited(f"Gemini is rate-limited until {rec.get('until')}")


def _harness_rate_limited(response) -> None:
    """Record a 429 from the harness (its detail carries until/estimated) and raise."""
    from datetime import datetime, timedelta
    from integrations import gemini_limit
    detail: dict = {}
    try:
        d = response.json().get("detail")
        detail = d if isinstance(d, dict) else {"message": str(d or "")}
    except Exception:
        detail = {"message": (response.text or "")[:300]}
    until = detail.get("until")
    estimated = bool(detail.get("estimated", False))
    if not until:
        until, estimated = (datetime.now().astimezone() + timedelta(seconds=60)).isoformat(timespec="seconds"), True
    gemini_limit.record(until, estimated, str(detail.get("message") or ""))
    try:
        hhmm = datetime.fromisoformat(until).astimezone().strftime("%H:%M")
    except ValueError:
        hhmm = str(until)
    logger.warning("Gemini hit its rate limit; next window about %s", hhmm)
    raise GeminiRateLimited(f"Gemini rate limit; next window about {hhmm}")


_OVERFLOW_TOKENS_RE = re.compile(r"request \((\d+) tokens\)")


def estimate_tokens(system: str, messages: List[Dict[str, str]]) -> int:
    from runtime.context_budget import estimate_tokens as _est  # lazy: runtime imports this module
    return _est(system, messages)


def lm_studio_max_context_length() -> int:
    """The most context a prompt may grow the model to (`lm_studio_max_context_length`)."""
    try:
        return max(4096, int(load_config().get("lm_studio_max_context_length") or 131072))
    except (TypeError, ValueError):
        return 131072


def local_max_output_tokens() -> int:
    try:
        return max(256, int(load_config().get("local_max_output_tokens") or 8192))
    except (TypeError, ValueError):
        return 8192


def _overflow_tokens(err: Any) -> Optional[int]:
    m = _OVERFLOW_TOKENS_RE.search(str(err))
    return int(m.group(1)) if m else None


def _round_ctx(n: int) -> int:
    return min(lm_studio_max_context_length(), max(lm_studio_context_length(), math.ceil(n / 8192) * 8192))


def reload_lm_studio_model(model: str, context: int) -> bool:
    """Load `model` again with `context` tokens (unload first: LM Studio keeps
    the old instance otherwise)."""
    lms_bin = find_lms_binary()
    if not lms_bin:
        logger.warning("lms binary not found: cannot reload '%s' with a larger context.", model)
        return False
    try:
        subprocess.run([lms_bin, "unload", model], capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        proc = subprocess.run([lms_bin, "load", model, "-c", str(context), "--parallel", "1", "-y"],
                              capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
        if proc.returncode != 0:
            logger.warning("lms load -c %d failed for '%s': %s", context, model, (proc.stderr or proc.stdout).strip()[:300])
        return proc.returncode == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reload LM Studio model '%s': %s", model, exc)
        return False


def load_config() -> Dict[str, Any]:
    default_config = {
        "gemini_url": GEMINI_DEFAULT_URL,
        "gemini_api_key": "",
        "gemini_model": "flash",
        "gemini_thinking_level": GEMINI_DEFAULT_EFFORT,
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": "qwen3.8-27b-gsq-rco",
        "ollama_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3.5:9b",
        "llamacpp_url": "http://127.0.0.1:8089/v1",
        "llamacpp_model": "qwen3.8-27b",
        "claude_url": CLAUDE_DEFAULT_URL,
        "claude_api_key": "",
        "claude_model": CLAUDE_DEFAULT_MODEL,
        # "auto" = whatever the tiers/selection say; "claude" = route the
        # produce_video model calls (visual planning, and BuzzEdit's moods,
        # topics and picture prompts) through the Claude proxy above.
        "produce_llm_provider": "auto",
        # The finished video: copied next to the recording ("beside_recording"),
        # into one folder ("folder" + produce_output_dir), or left where
        # BuzzEdit wrote it ("buzzedit"); Explorer shows it when done.
        "produce_output_mode": "beside_recording",
        "produce_output_dir": "",
        "produce_reveal_output": True,
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
        "local_only": True,
        "prefer_gemini": False,
        "selected_provider": "lm_studio",
        "lm_studio_context_length": 32768,
        "lm_studio_max_context_length": 65536,
        "local_max_output_tokens": 8192,
    }

    config = dict(default_config)

    # 1. Environment variables provide baseline defaults
    env_keys = {
        "GEMINI_URL": "gemini_url",
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_MODEL": "gemini_model",
        "GEMINI_THINKING_LEVEL": "gemini_thinking_level",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "LM_STUDIO_URL": "lm_studio_url",
        "LM_STUDIO_MODEL": "lm_studio_model",
        "OLLAMA_URL": "ollama_url",
        "OLLAMA_MODEL": "ollama_model",
        "LLAMACPP_URL": "llamacpp_url",
        "LLAMACPP_MODEL": "llamacpp_model",
        "CLAUDE_URL": "claude_url",
        "CLAUDE_API_KEY": "claude_api_key",
        "CLAUDE_MODEL": "claude_model",
        "SELECTED_PROVIDER": "selected_provider"
    }
    for env_key, config_key in env_keys.items():
        if os.environ.get(env_key):
            config[config_key] = os.environ[env_key]

    if os.environ.get("LOCAL_ONLY") is not None:
        config["local_only"] = os.environ["LOCAL_ONLY"].lower() in ["true", "1", "yes"]

    if os.environ.get("PREFER_GEMINI"):
        val = os.environ["PREFER_GEMINI"].lower() in ["true", "1", "yes"]
        config["prefer_gemini"] = val

    # 2. Saved configuration in config.json overrides environment defaults
    # so creator settings persist across reloads until explicitly reset
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                for k, v in file_config.items():
                    # save_config writes the whole merged dict, so an unset key
                    # lands in the file as "". Blank means "not set": it must
                    # not hide a real value from the environment.
                    if v == "" and config.get(k):
                        continue
                    config[k] = v
        except Exception as e:
            logger.error(f"Error loading LLM config: {e}")

    # A config file written before v9 has no tiers, and a partial one must not
    # lose a tier: fill in whatever is missing.
    tiers = config.get("tiers")
    merged = {k: dict(v) for k, v in DEFAULT_TIERS.items()}
    if isinstance(tiers, dict):
        for name, entry in tiers.items():
            if isinstance(entry, dict):
                merged.setdefault(name, {}).update(entry)
    config["tiers"] = merged

    return config


def save_config(config: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving LLM config: {e}")

def claude_settings(config: Dict[str, Any]) -> Dict[str, str]:
    """`{url, api_key, model}` for the Claude proxy, defaults filled in."""
    return {
        "url": str(config.get("claude_url") or CLAUDE_DEFAULT_URL).rstrip("/"),
        "api_key": str(config.get("claude_api_key") or os.environ.get("CLAUDE_API_KEY", "") or ""),
        "model": str(config.get("claude_model") or CLAUDE_DEFAULT_MODEL),
    }


def claude_configured(config: Dict[str, Any]) -> bool:
    return bool(claude_settings(config)["api_key"])


def probe_claude(config: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Dict[str, Any]:
    """Is the Claude proxy up and does our key open it? Never raises.

    `GET /v1/models` needs the key, so a 200 proves both at once; a 401/403
    says the proxy is there but the key is wrong; a connection error says it
    is not running (`start-server.bat start` in ../claudeAPI)."""
    cfg = claude_settings(config or load_config())
    result: Dict[str, Any] = {"url": cfg["url"], "model": cfg["model"], "key_set": bool(cfg["api_key"]),
                              "online": False, "authorized": False, "models": [], "message": ""}
    if not cfg["api_key"]:
        result["message"] = "No API key saved for the Claude proxy."
    try:
        resp = requests.get(f"{cfg['url']}/models", headers={"Authorization": f"Bearer {cfg['api_key']}"},
                            timeout=timeout)
    except requests.RequestException as exc:
        result["message"] = f"Claude proxy not reachable at {cfg['url']} ({exc.__class__.__name__})."
        return result
    result["online"] = True
    if resp.status_code in (401, 403):
        result["message"] = "Claude proxy is running but rejected the API key."
        return result
    if resp.status_code != 200:
        result["message"] = f"Claude proxy answered HTTP {resp.status_code}."
        return result
    result["authorized"] = True
    try:
        data = resp.json().get("data") or []
        result["models"] = [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")][:40]
    except Exception:  # noqa: BLE001 - a model list is a nicety
        pass
    result["message"] = f"Claude proxy online at {cfg['url']} (model: {cfg['model']})."
    return result


def gemini_settings(config: Dict[str, Any]) -> Dict[str, str]:
    """`{url, api_key, model, thinking_level}` for Gemini (local harness or cloud API)."""
    return {
        "url": str(config.get("gemini_url") or GEMINI_DEFAULT_URL).rstrip("/"),
        "api_key": str(config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "") or ""),
        "model": str(config.get("gemini_model") or GEMINI_DEFAULT_MODEL),
        "thinking_level": str(config.get("gemini_thinking_level") or GEMINI_DEFAULT_EFFORT).lower(),
    }


def is_local_gemini(config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = gemini_settings(config or load_config())
    url = cfg["url"].lower()
    return "127.0.0.1" in url or "localhost" in url


def probe_gemini(config: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Dict[str, Any]:
    """Is the local Gemini harness server (http://127.0.0.1:8001) or Google Gemini API reachable? Never raises."""
    cfg = gemini_settings(config or load_config())
    is_local = is_local_gemini(cfg)
    result: Dict[str, Any] = {
        "url": cfg["url"],
        "model": cfg["model"],
        "thinking_level": cfg.get("thinking_level", GEMINI_DEFAULT_EFFORT),
        "thinking_levels": list(GEMINI_EFFORT_LEVELS),
        "key_set": bool(cfg["api_key"]),
        "online": False,
        "is_local": is_local,
        "auth_mode": "",
        "models": ["flash", "argon", "flash-lite", "pro", "gemini-2.5-flash"],
        "message": "",
    }
    if is_local:
        try:
            resp = requests.get(f"{cfg['url']}/openapi.json", timeout=timeout)
            if resp.status_code == 200:
                result["online"] = True
                result["auth_mode"] = "oauth-personal (Antigravity CLI keyring)"
                result["message"] = f"Gemini harness online at {cfg['url']} (Zero API keys — Personal OAuth)."
                return result
        except requests.RequestException as exc:
            result["message"] = f"Gemini harness not reachable at {cfg['url']} ({exc.__class__.__name__})."

    if cfg["api_key"]:
        result["online"] = True
        result["auth_mode"] = "api_key"
        result["message"] = "Google Gemini Cloud API configured with API key."
        return result

    if not result["message"]:
        result["message"] = f"Gemini harness not reachable at {cfg['url']} and no Gemini API key configured."
    return result


_gpu_busy_cache: Dict[str, float] = {"at": 0.0, "busy": 0.0}


def _gpu_owned_by_render() -> bool:
    """True while a video render owns the GPU: this Studio's produce_video
    run, or any BuzzEdit job (asked at most every 15s -- it is an HTTP call)."""
    try:
        from app.api.produce_api import buzzedit_job_active, render_in_progress
    except Exception:
        return False
    try:
        if render_in_progress():
            return True
        now = time.monotonic()
        if now - _gpu_busy_cache["at"] > 15.0:
            _gpu_busy_cache["busy"] = 1.0 if buzzedit_job_active() else 0.0
            _gpu_busy_cache["at"] = now
        return bool(_gpu_busy_cache["busy"])
    except Exception:
        return False


def _defer_gpu_providers(order: List[str]) -> List[str]:
    """While a render owns the GPU, try every non-GPU provider first.

    A local model loaded beside ComfyUI is what starved a real render (a
    ~10 GB LM Studio model left Wan 2.2 ~5.5 GB, clips ran at ~470 s/step and
    timed out). Only providers the order already allows are reordered -- this
    never adds a cloud provider Strict Local ruled out, so with nothing else
    permitted the local model is still used.
    """
    if not any(p in LOCAL_PROVIDERS for p in order) or all(p in LOCAL_PROVIDERS for p in order):
        return order
    if not _gpu_owned_by_render():
        return order
    return [p for p in order if p not in LOCAL_PROVIDERS] + [p for p in order if p in LOCAL_PROVIDERS]



#: A local model call waits for BuzzEdit's reel as long as the reel keeps moving; it
#: only gives up when the reel's progress has not changed for this long (a stuck
#: job). A fixed 45-min ceiling let Gemma load beside Wan on every long story reel
#: (19-45 shots run hours) -- Fable review, 2026-10-24.
REEL_RENDER_STALL_S = 40 * 60.0


def wait_for_reel_render() -> None:
    """Hold a local-model call while BuzzEdit is generating a reel: loading the LLM
    then takes the VRAM ComfyUI is using (2026-10-23: a clip timed out three times
    while a reel's poem search and an overnight story batch loaded Gemma). The
    reel's own model steps run before its render starts, so they never wait here."""
    try:
        from integrations.buzzedit_client import BuzzEditClient
        client = BuzzEditClient()
        last_seen, last_change = None, time.time()
        told = False
        while client.vibe_reel_busy():
            try:
                busy = client._get("/api/reels/busy", timeout=(5, 30)).json()
                job = client.vibe_reel_job(busy["job_id"]) if busy.get("job_id") else {}
                seen = (job.get("progress"), job.get("message"))
            except Exception:  # noqa: BLE001 - cannot read progress: count it as unchanged
                seen = last_seen
            # The master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1) holds the
            # reel between shots on purpose -- that is not a stall, and this
            # wait must not give up while it is on, however long it lasts.
            try:
                from app.services import master_control
                paused = master_control.is_paused()
            except Exception:  # noqa: BLE001
                paused = False
            if paused:
                last_change = time.time()
            elif seen != last_seen:
                last_seen, last_change = seen, time.time()
            elif time.time() - last_change > REEL_RENDER_STALL_S:
                logger.warning("Reel render shows no progress for %d min; the model call goes ahead",
                               int(REEL_RENDER_STALL_S // 60))
                break
            if not told:
                logger.info("Local model call waiting: BuzzEdit is rendering a reel")
                told = True
            time.sleep(20)
    except Exception as e:  # noqa: BLE001 - never block a call on the check itself
        logger.debug("reel render check skipped: %s", e)


#: What the PC keeps free when a local model loads (creator rule 2026-10-26:
#: "models one at a time, or at least 1-2 GB VRAM and 4-5 GB RAM remain; the
#: PC must not lag or hang"). Tonight a Gemma load beside a render and a voice
#: timed out after 600 s and the fallback loaded a second model on Ollama.
MIN_FREE_VRAM_MIB = 1536
MIN_FREE_RAM_MIB = 5120
#: A call waits this long for room at most, then goes ahead with a warning --
#: a stuck GPU job must not wedge every script forever.
LOCAL_HEADROOM_MAX_WAIT_S = 6 * 3600.0
LOCAL_HEADROOM_POLL_S = 20.0

_free_cache: Dict[str, Any] = {"at": 0.0, "value": (None, None)}


def free_memory_mib() -> Tuple[Optional[int], Optional[int]]:
    """(free VRAM, free RAM) in MiB; None for what cannot be read. Cached 5 s."""
    now = time.monotonic()
    if now - _free_cache["at"] < 5.0:
        return _free_cache["value"]
    vram: Optional[int] = None
    ram: Optional[int] = None
    try:
        import shutil
        exe = shutil.which("nvidia-smi")
        if exe:
            text = subprocess.run([exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            used, total = (float(p.strip()) for p in text.splitlines()[0].split(","))
            vram = int(total - used)
    except Exception:  # noqa: BLE001 - no NVIDIA card or driver busy: unknown, not full
        vram = None
    try:
        import psutil
        ram = int(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:  # noqa: BLE001
        ram = None
    _free_cache.update(at=now, value=(vram, ram))
    return vram, ram


def local_headroom_problem(need_mib: int, loaded: bool) -> Optional[str]:
    """Why loading (or, `loaded`, using) a local model now would leave the PC
    too little room, or None. A model already in memory adds no VRAM; only
    the RAM floor applies to it."""
    vram, ram = free_memory_mib()
    if not loaded and vram is not None and vram < need_mib + MIN_FREE_VRAM_MIB:
        return (f"{vram} MiB VRAM free; the model needs ~{need_mib} MiB and {MIN_FREE_VRAM_MIB} MiB must "
                "stay free")
    if ram is not None and ram < MIN_FREE_RAM_MIB:
        return f"{ram} MiB RAM free; {MIN_FREE_RAM_MIB} MiB must stay free"
    return None


def _ollama_model_loaded(model: str) -> bool:
    try:
        resp = requests.get("http://127.0.0.1:11434/api/ps", timeout=2)
        names = {str(m.get("name") or "") for m in (resp.json().get("models") or [])}
        return model in names or any(n.split(":")[0] == model.split(":")[0] for n in names if model)
    except Exception:  # noqa: BLE001 - Ollama down: nothing of it is loaded
        return False


def wait_for_local_headroom(provider: str, model: str, loaded: bool) -> None:
    """Hold a local model call until it fits with room to spare (above)."""
    need = estimate_model_mib(model)
    started = time.time()
    told = False
    asked_free = False
    while True:
        problem = local_headroom_problem(need, loaded)
        if not problem:
            if told:
                logger.info("Local %s call goes ahead: there is room now (%s).", provider, model)
            return
        if not asked_free and not _gpu_owned_by_render():
            # Nothing is rendering: the card is full of models cached from the
            # last job, not work. BuzzEdit hands it back once, then we measure.
            asked_free = True
            try:
                from integrations.buzzedit_client import BuzzEditClient
                client = BuzzEditClient()
                if client.narration_busy() or client.vibe_reel_busy():
                    raise RuntimeError("BuzzEdit is making a voice or a reel")
                client.clear_vram()
                _free_cache["at"] = 0.0
                continue
            except Exception as exc:  # noqa: BLE001 - BuzzEdit down: nothing of its to free
                logger.debug("headroom: could not ask BuzzEdit to free the GPU (%s)", exc)
        if time.time() - started > LOCAL_HEADROOM_MAX_WAIT_S:
            logger.warning("Local %s call waited %d h for room (%s); going ahead.", provider,
                           int(LOCAL_HEADROOM_MAX_WAIT_S // 3600), problem)
            return
        if not told:
            logger.info("Local %s call for %s waits for room: %s.", provider, model, problem)
            told = True
        time.sleep(LOCAL_HEADROOM_POLL_S)
        _free_cache["at"] = 0.0


class LLMService:
    def __init__(self, forced_provider: Optional[str] = None, purpose: str = "agents",
                 fallback_provider: Optional[str] = None, effort: Optional[str] = None):
        self.config = load_config()
        # "production" (video planning) or "agents" (everything else): picks
        # which of the two Settings thinking switches applies to local calls.
        self.purpose = purpose
        # True when the most recent generate_text() call produced canned text
        # because every configured provider failed. Callers must surface this
        # rather than presenting fabricated output as a model response.
        self.last_response_simulated = False
        # Which provider answered the most recent call (None when simulated).
        self.last_provider: Optional[str] = None
        # A provider to try before anything else -- how produce_video routes
        # its planning calls to Claude without touching the global selection.
        # The normal order still follows, so a proxy that is down falls back.
        self.forced_provider = (forced_provider or "").strip().lower() or None
        # A provider to try AFTER the tier's and the selected one, but before
        # the generic fallback -- and, like a forced provider, allowed under
        # Strict Local because the caller named it (produce_video adds the
        # Claude proxy this way when the production switch is on "auto").
        self.fallback_provider = (fallback_provider or "").strip().lower() or None
        # Explicit reasoning/effort override for Gemini harness ("low", "medium", "high", "max")
        self.forced_effort = (effort or "").strip().lower() or None
        # True only for forecasts: the provider order as it is with no render on the GPU.
        self.ignore_render = False

    def reload_config(self):
        self.config = load_config()

    def gemini_effort_level(self, override: Optional[str] = None) -> str:
        """Determines the Gemini thinking/effort level (low, medium, high, max).
        Valid levels: low, medium, high, max.
        Explicit override or forced_effort is honored first.
        If not explicitly overridden and thinking_enabled() is False, returns 'low'.
        Otherwise returns config['gemini_thinking_level'] (default 'high')."""
        choice = (override or self.forced_effort or "").strip().lower()
        if choice in GEMINI_EFFORT_LEVELS:
            return choice
        if not self.thinking_enabled():
            return "low"
        cfg_level = str(self.config.get("gemini_thinking_level") or GEMINI_DEFAULT_EFFORT).strip().lower()
        if cfg_level in GEMINI_EFFORT_LEVELS:
            return cfg_level
        return GEMINI_DEFAULT_EFFORT

    def _route(self) -> Dict[str, str]:
        """The current job's route when it names a provider, else {}."""
        job = _CURRENT_JOB.get()
        if not job:
            return {}
        route = job_routes(self.config).get(job) or {}
        return route if route.get("provider") else {}

    def _tier_settings(self, tier: Optional[str]) -> Dict[str, Any]:
        # A routed job overrides the persona's tier (the Model Routing window).
        route = self._route()
        if route:
            return route
        entry = (self.config.get("tiers") or {}).get(tier) if tier else None
        return entry if isinstance(entry, dict) else {}

    def _provider_order(self, tier: Optional[str] = None) -> List[str]:
        """Which providers to try, in order: the tier's own first, then the
        globally selected one, then everything else (roadmap v9, F1).

        When local_only is True (default) or the selected provider is in
        LOCAL_PROVIDERS, all cloud providers (Gemini, OpenAI) are strictly
        filtered out to ensure zero data leaves the machine.
        """
        order: List[str] = []
        explicit: List[str] = []
        if self.forced_provider:
            order.append(self.forced_provider)
            explicit.append(self.forced_provider)
        tier_provider = str(self._tier_settings(tier).get("provider") or "").strip().lower()
        # A copy of the wanted local model already in Ollama is used as it is (one model
        # in memory at a time); `_model_for("ollama")` answers with that copy's name.
        wanted = str(self._tier_settings(tier).get("model") or self.config.get("lm_studio_model") or "")
        if tier_provider in ("", "lm_studio", "llamacpp") and ollama_copy_of(wanted):
            order.append("ollama")
            explicit.append("ollama")
        if tier_provider:
            order.append(tier_provider)
            explicit.append(tier_provider)
        route_fallback = str(self._route().get("fallback") or "").strip().lower()
        if route_fallback:
            order.append(route_fallback)
            explicit.append(route_fallback)

        provider = self.config.get("selected_provider") or os.environ.get("SELECTED_PROVIDER")
        if not provider:
            provider = "lm_studio" if not self.config.get("prefer_gemini", False) else "gemini"
        order.append(str(provider).lower())
        explicit.append(str(provider).lower())
        if self.fallback_provider:
            order.append(self.fallback_provider)
            explicit.append(self.fallback_provider)

        is_local_only = bool(self.config.get("local_only", False))
        if is_local_only:
            order.extend(LOCAL_FALLBACK_ORDER)
        else:
            order.extend(FALLBACK_ORDER)

        # Writing jobs never reach Claude by themselves (the creator, 2026-10-29: "remove
        # Claude from script writing altogether, no fallback, a manual switch only"): only a
        # route that names Claude as the job's own provider, or a forced Claude call, uses it.
        job = _CURRENT_JOB.get()
        no_auto_claude = (job in self.config.get("claude_manual_only_jobs", CLAUDE_MANUAL_ONLY_JOBS)
                          and tier_provider != "claude" and self.forced_provider != "claude")

        seen, unique = set(), []
        for name in order:
            if not name or name in seen:
                continue
            if name == "claude" and no_auto_claude:
                continue
            if is_local_only and name not in LOCAL_PROVIDERS:
                # The Claude proxy and local Gemini harness are exceptions: allowed under Strict
                # Local when the user asked for them by name, never as an implicit fallback.
                if name == "claude" and name in explicit:
                    pass
                elif name == "gemini" and name in explicit and is_local_gemini(self.config):
                    pass
                else:
                    continue
            seen.add(name)
            unique.append(name)
        return unique if getattr(self, "ignore_render", False) else _defer_gpu_providers(unique)

    def _model_for(self, provider: str, tier: Optional[str]) -> str:
        route = self._route()
        if route and provider == "claude" and route.get("fallback") == "claude" and route.get("provider") != "claude":
            # A routed job that falls back to Claude (Gemma busy or down) gets a
            # model fit to write with, not the cheap default (haiku).
            return route.get("fallback_model") or "sonnet"
        tier_cfg = self._tier_settings(tier)
        tier_p = str(tier_cfg.get("provider") or "").strip().lower()
        override = str(tier_cfg.get("model") or "").strip()
        if override and (not tier_p or tier_p == provider.lower()):
            return override
        if provider.lower() == "ollama":
            copy = ollama_copy_of(override or str(self.config.get("lm_studio_model") or ""))
            if copy:
                return copy
        return {
            "gemini": self.config.get("gemini_model", "gemini-1.5-flash"),
            "openai": self.config.get("openai_model", "gpt-4o-mini"),
            "lm_studio": self.config.get("lm_studio_model", "qwen3.8-27b-gsq-rco"),
            "ollama": self.config.get("ollama_model", "qwen3.5:9b"),
            "llamacpp": self.config.get("llamacpp_model", "qwen3.8-27b"),
            "claude": claude_settings(self.config)["model"],
        }.get(provider, "")

    def _chat_claude(
        self,
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        """One call to the Claude proxy. `response_format` is deliberately not
        sent: the proxy renders schemas into the prompt itself, and every
        JSON-wanting prompt in this codebase already says "JSON only"."""
        cfg = claude_settings(self.config)
        if not cfg["api_key"]:
            raise Exception("Claude proxy: no API key configured (Settings -> Claude API).")
        return self._chat_openai_compat(
            f"{cfg['url']}/chat/completions", {"Authorization": f"Bearer {cfg['api_key']}"},
            model, system_prompt, messages, False, temperature, timeout=CLAUDE_TIMEOUT_SECONDS,
        )

    def _local_url(self, provider: str) -> str:
        if provider == "ollama":
            default = "http://localhost:11434/v1"
            key = "ollama_url"
        elif provider == "lm_studio":
            default = "http://localhost:1234/v1"
            key = "lm_studio_url"
        else:
            default = "http://127.0.0.1:8089/v1"
            key = "llamacpp_url"
        return str(self.config.get(key) or default).rstrip("/")

    def _is_lm_studio_model_loaded(self, model_name: str) -> bool:
        """Check if the requested model is already resident in LM Studio VRAM/RAM."""
        if not model_name:
            return False
        try:
            base_url = self._local_url("lm_studio").replace("/v1", "")
            r = requests.get(f"{base_url}/api/v0/models", timeout=0.8)
            if r.status_code == 200:
                data = r.json().get("data", [])
                exact = exact_model_id(model_name, [m.get("id", "") for m in data])
                if exact:
                    return any(m.get("id") == exact and m.get("state") == "loaded" for m in data)
                for m in data:
                    mid = m.get("id", "")
                    if (m.get("state") == "loaded") and (mid == model_name or models_match(model_name, mid)):
                        return True
        except Exception:
            pass
        return False

    def _resolve_lm_studio_model(self, requested_model: Optional[str] = None) -> str:
        """Resolve a configured model identifier to the actual ID recognized by LM Studio."""
        try:
            base_url = self._local_url("lm_studio").replace("/v1", "")
            r = requests.get(f"{base_url}/api/v0/models", timeout=0.8)
            if r.status_code == 200:
                data = r.json().get("data", [])
                loaded_models = [m.get("id") for m in data if m.get("state") == "loaded"]
                available_models = [m.get("id") for m in data]

                # 0. A real LM Studio ID is used as-is, loaded or not (JIT loads it).
                exact = exact_model_id(requested_model, available_models)
                if exact:
                    return exact

                # 1. Match against loaded models first
                if requested_model:
                    for mid in loaded_models:
                        if models_match(requested_model, mid):
                            return mid

                # 2. Match against available models
                if requested_model:
                    for mid in available_models:
                        if models_match(requested_model, mid):
                            return mid

                # 3. Fall back to currently loaded model
                if loaded_models:
                    return loaded_models[0]

                # 4. Fall back to first available model
                if available_models:
                    return available_models[0]
        except Exception as e:
            logger.debug("Could not query LM Studio models: %s", e)
        return requested_model or "qwen3.8-27b-gsq-rco"

    def _lm_studio_ready(self, model: str) -> None:
        """Load the model ourselves when it is not in memory, with the Studio's
        context length. Left to LM Studio's just-in-time load (which is what
        happens after every idle unload) it comes up with LM Studio's default
        context, and a long prompt is refused. Never raises."""
        try:
            if model and not self._is_lm_studio_model_loaded(model):
                ensure_local_model_loaded("lm_studio", model)
            elif model and time.time() - _PARALLEL_CHECKED.get(model, 0) > 300:
                # Loaded by someone else (LM Studio's own JIT load, its UI) with
                # several slots: one prompt then gets only a share of the context.
                _PARALLEL_CHECKED[model] = time.time()
                slots = lm_studio_loaded_parallel(model)
                if slots and slots > 1:
                    ctx = lm_studio_loaded_context(model) or lm_studio_context_length()
                    logger.warning("LM Studio holds '%s' with %d parallel slots (%d tokens each); "
                                   "reloading with one slot.", model, slots, ctx // slots)
                    reload_lm_studio_model(model, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not pre-load LM Studio model '%s': %s", model, exc)

    def _grow_lm_studio_context(self, model: str, error: Optional[Exception] = None,
                                need: Optional[int] = None) -> bool:
        """Reload `model` with more context. After a "prompt exceeds the
        context" refusal (`error`) or when the prompt is known to need `need`
        tokens: the context wanted is the size of the prompt (+15%, + the
        output reserve) rounded up to 8k, never above the maximum. With no
        count it is the Studio's setting. True when the call is worth a retry."""
        try:
            if need is None and not _CONTEXT_OVERFLOW_RE.search(str(error)):
                return False
            count = need or _overflow_tokens(error) or 0
            out_reserve = local_max_output_tokens()
            max_ctx = lm_studio_max_context_length()
            wanted = _round_ctx(int(count * 1.15) + out_reserve) if count else lm_studio_context_length()
            have = lm_studio_loaded_context(model)
            if have is None or not (have < wanted <= max_ctx):
                return False
            logger.warning("LM Studio context for '%s': %d -> %d tokens (prompt does not fit); reloading and retrying.",
                           model, have, wanted)
            return reload_lm_studio_model(model, wanted)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not grow LM Studio's context for '%s': %s", model, exc)
            return False

    def _lm_studio_fit(self, model: str, system_prompt: str, messages: List[Dict[str, str]]):
        """Inside the gate, before the request: grow the loaded context to the
        prompt, or compress the prompt when it exceeds the maximum. Returns
        (system, messages); raises ContextTooLarge when nothing makes it fit."""
        out_reserve = local_max_output_tokens()
        max_ctx = lm_studio_max_context_length()
        need = estimate_tokens(system_prompt, messages) + out_reserve
        if need > max_ctx:
            from runtime.context_budget import fit_messages
            system_prompt, messages = fit_messages(system_prompt, messages, max_ctx - out_reserve)
            after = estimate_tokens(system_prompt, messages) + out_reserve
            if after > max_ctx:
                raise ContextTooLarge(f"prompt ~{need} tok > {max_ctx}")
            logger.warning("Prompt ~%d tokens exceeds the %d maximum: trimmed to ~%d.", need, max_ctx, after)
            need = after
        loaded = lm_studio_loaded_context(model) or lm_studio_context_length()
        if need > loaded:
            self._grow_lm_studio_context(model, need=max(1, need - out_reserve))
        return system_prompt, messages

    def _wait_for_room(self, provider: str, model: str) -> None:
        """Hold the call until the model fits with room to spare
        (`wait_for_local_headroom`). A llama.cpp server that answers has its
        model loaded already."""
        if provider == "lm_studio":
            loaded = self._is_lm_studio_model_loaded(model)
        elif provider == "ollama":
            loaded = _ollama_model_loaded(model)
        else:
            loaded = True
        wait_for_local_headroom(provider, model, loaded)

    def _sentinel_allows(self, provider: str, tier: Optional[str] = None) -> bool:
        """May we send a request that could make a model load? (roadmap v10, S1)"""
        if provider != "lm_studio":
            return True
        model = self._model_for(provider, tier)
        resolved_model = self._resolve_lm_studio_model(model)
        if self._is_lm_studio_model_loaded(resolved_model):
            return True
        mib = estimate_model_mib(resolved_model)
        try:
            from integrations.sentinel_client import client as sentinel_client

            granted, details = sentinel_client().query(mib=mib)
        except Exception as exc:
            # A guardian we cannot even talk to must not stop the Studio.
            logger.debug("Sentinel query failed (%s); proceeding with lm_studio.", exc)
            return True
        if granted:
            return True
        holders = ", ".join(
            str(b.get("client") or b.get("process") or "?") for b in (details.get("blockers") or [])
        )
        logger.warning(
            "Sentinel refused %d MiB for lm_studio (%s%s); evaluating fallback.",
            mib,
            details.get("reason") or "no reason given",
            f"; held by {holders}" if holders else "",
        )
        # If Strict Local is on and no other active client blocks the card, allow LM Studio
        # to manage CPU offloading rather than stranding the user with simulated text.
        if self.config.get("local_only", True) and not holders:
            logger.info("Sentinel refused full VRAM, but LM Studio offloading is available; allowing request.")
            return True
        return False

    @idle_offload.tracked
    @_metered
    def generate_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool = False,
        tier: Optional[str] = None,
        temperature: Optional[float] = None,
        effort: Optional[str] = None,
    ) -> str:
        """
        Multi-turn generation: `messages` is an ordered list of
        {"role": "user"|"assistant", "content": ...}. Same provider order and
        fallback rules as generate_text; the last user message is what the
        simulated fixture answers when no provider is reachable.
        """
        self.reload_config()
        self.last_response_simulated = False
        self.last_provider = None
        temp = DEFAULT_TEMPERATURE if temperature is None else float(temperature)
        too_large: Optional[ContextTooLarge] = None

        for current_p in self._provider_order(tier):
            self.last_provider = current_p
            model = self._model_for(current_p, tier)
            self.last_model = model
            if current_p == "gemini":
                gem_url = self.config.get("gemini_url") or GEMINI_DEFAULT_URL
                if is_local_gemini(self.config):
                    try:
                        thinking_lvl = self.gemini_effort_level(effort)
                        logger.info("Attempting chat via local Gemini harness at %s (model: %s, effort: %s)...", gem_url, model, thinking_lvl)
                        return self._chat_gemini_harness(gem_url, model, system_prompt, messages, require_json, temp, effort=effort)
                    except Exception as e:
                        logger.warning(f"Local Gemini harness chat failed: {e}.")
                        # A one-off empty reply or rate-limit blip (2026-10-26) sent whole
                        # strategist turns to the local model, which then fought the
                        # narration engine for the GPU. Wait once and try Gemini again --
                        # but not after a timeout: the same prompt times out again, and
                        # every chat turn waited 4.5 min before falling back (2026-10-26).
                        if "timed out" not in str(e).lower() and not isinstance(e, GeminiRateLimited):
                            try:
                                time.sleep(GEMINI_RETRY_WAIT_S)
                                logger.info("Retrying the local Gemini harness once after %ss...", GEMINI_RETRY_WAIT_S)
                                return self._chat_gemini_harness(gem_url, model, system_prompt, messages, require_json, temp, effort=effort)
                            except Exception as e2:
                                logger.warning(f"Local Gemini harness retry failed: {e2}.")
                api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                if api_key and not self.config.get("local_only", False):
                    try:
                        logger.info("Attempting chat via Google Gemini API...")
                        return self._chat_gemini(api_key, system_prompt, messages, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"Gemini API chat failed: {e}.")
            elif current_p == "openai":
                api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting chat via OpenAI API...")
                        return self._chat_openai_compat(
                            "https://api.openai.com/v1/chat/completions",
                            {"Authorization": f"Bearer {api_key}"},
                            model, system_prompt, messages, require_json, temp,
                        )
                    except Exception as e:
                        logger.warning(f"OpenAI API chat failed: {e}.")
            elif current_p == "claude":
                if claude_configured(self.config):
                    try:
                        logger.info("Attempting chat via the Claude proxy (model: %s)...", model)
                        return self._chat_claude(model, system_prompt, messages, temp)
                    except Exception as e:
                        logger.warning(f"Claude proxy chat failed: {e}.")
            elif current_p in LOCAL_PROVIDERS:
                if not self._sentinel_allows(current_p, tier):
                    continue
                wait_for_reel_render()
                if current_p == "lm_studio":
                    model = self._resolve_lm_studio_model(model)
                self._wait_for_room(current_p, model)
                if current_p == "lm_studio":
                    self._lm_studio_ready(model)
                idle_offload.mark_used(current_p)
                url = self._local_url(current_p)

                def chat_local():
                    with (_LM_STUDIO_GATE if current_p == "lm_studio" else contextlib.nullcontext()):
                        sp, ms = system_prompt, messages
                        if current_p == "lm_studio":
                            sp, ms = self._lm_studio_fit(model, sp, ms)

                        def send():
                            return self._with_local_json_mode(require_json, lambda json_mode: self._chat_openai_compat(
                                f"{url}/chat/completions", {}, model,
                                sp, ms, json_mode, temp, timeout=self._local_timeout(),
                                reasoning_effort=self._local_reasoning_effort(current_p),
                                max_tokens=local_max_output_tokens(),
                            ))

                        try:
                            return send()
                        except Exception as e:  # noqa: BLE001
                            if current_p == "lm_studio" and self._grow_lm_studio_context(model, e):
                                return send()
                            raise

                try:
                    logger.info(f"Attempting chat via local {current_p} at {url} (model: {model})...")
                    return chat_local()
                except ContextTooLarge as e:
                    logger.warning(f"{current_p} chat failed: {e}.")
                    too_large = e
                except Exception as e:
                    logger.warning(f"{current_p} chat failed: {e}.")

        if too_large is not None:
            raise too_large
        if not _simulation_enabled():
            msg = (
                "No local LLM provider is reachable (LM Studio / Ollama / llama.cpp). "
                "Cloud providers are blocked by Strict Local Mode to ensure zero data leaves your PC."
                if self.config.get("local_only", True)
                else "No LLM provider is reachable. Check your API keys and that the selected model is available in Settings."
            )
            raise LLMUnavailable(msg)
        logger.warning("No LLM provider succeeded; returning simulated content.")
        self.last_response_simulated = True
        self.last_provider = None
        from dev.fixtures import generate_simulated_response

        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        return generate_simulated_response(system_prompt, last_user, require_json)

    def _chat_openai_compat(
        self,
        url: str,
        headers: Dict[str, str],
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: int = 90,
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages
        )
        payload: Dict[str, Any] = {"model": model, "messages": payload_messages, "temperature": temperature}
        if require_json:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        response = requests.post(
            url, headers={"Content-Type": "application/json", **headers}, json=payload, timeout=timeout
        )
        if response.status_code != 200:
            raise Exception(f"{url} returned code {response.status_code}: {response.text[:300]}")
        resp_json = response.json()
        _CALL.usage = resp_json.get("usage") if isinstance(resp_json.get("usage"), dict) else None
        try:
            msg = resp_json["choices"][0]["message"]
            text = msg.get("content") or msg.get("reasoning_content") or ""
            return _non_empty_reply(text, model)
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse chat response payload: {resp_json}. Error: {e}")

    def _chat_gemini(
        self,
        api_key: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        configured_model = model_name or self.config.get("gemini_model", "gemini-1.5-flash")
        candidate_models = list(dict.fromkeys(
            [configured_model, "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
        ))
        contents = [
            {"role": "user" if m.get("role") == "user" else "model", "parts": [{"text": m.get("content", "")}]}
            for m in messages
        ]
        last_error = None
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload: Dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": temperature}}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
            if require_json:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            try:
                response = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
                if response.status_code == 200:
                    return response.json()["candidates"][0]["content"]["parts"][0]["text"]
                last_error = f"Gemini API ({model}) returned code {response.status_code}: {response.text[:200]}"
                logger.warning(last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Error calling Gemini model {model}: {e}")
        raise Exception(f"All Gemini models failed. Last error: {last_error}")

    @idle_offload.tracked
    @_metered
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        require_json: bool = False,
        tier: Optional[str] = None,
        temperature: Optional[float] = None,
        effort: Optional[str] = None,
    ) -> str:
        self.reload_config()
        self.last_response_simulated = False
        self.last_provider = None
        temp = DEFAULT_TEMPERATURE if temperature is None else float(temperature)
        too_large: Optional[ContextTooLarge] = None

        for current_p in self._provider_order(tier):
            self.last_provider = current_p
            model = self._model_for(current_p, tier)
            self.last_model = model
            if current_p == "gemini":
                gem_url = self.config.get("gemini_url") or GEMINI_DEFAULT_URL
                if is_local_gemini(self.config):
                    try:
                        thinking_lvl = self.gemini_effort_level(effort)
                        logger.info("Attempting generation via local Gemini harness at %s (model: %s, effort: %s)...", gem_url, model, thinking_lvl)
                        return self._call_gemini_harness(gem_url, model, system_prompt, user_prompt, require_json, temp, effort=effort)
                    except Exception as e:
                        logger.warning(f"Local Gemini harness call failed: {e}.")
                api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                if api_key and not self.config.get("local_only", False):
                    try:
                        logger.info("Attempting generation via Google Gemini API...")
                        return self._call_gemini(api_key, system_prompt, user_prompt, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"Gemini API call failed: {e}.")
            elif current_p == "openai":
                api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting generation via OpenAI API...")
                        return self._call_openai(api_key, system_prompt, user_prompt, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"OpenAI API call failed: {e}.")
            elif current_p == "claude":
                if claude_configured(self.config):
                    try:
                        logger.info("Attempting generation via the Claude proxy (model: %s)...", model)
                        return self._chat_claude(model, system_prompt,
                                                 [{"role": "user", "content": user_prompt}], temp)
                    except Exception as e:
                        logger.warning(f"Claude proxy call failed: {e}.")
            elif current_p in LOCAL_PROVIDERS:
                if not self._sentinel_allows(current_p, tier):
                    continue
                if current_p == "lm_studio":
                    model = self._resolve_lm_studio_model(model)
                self._wait_for_room(current_p, model)
                if current_p == "lm_studio":
                    self._lm_studio_ready(model)
                idle_offload.mark_used(current_p)
                url = self._local_url(current_p)

                def call_local():
                    with (_LM_STUDIO_GATE if current_p == "lm_studio" else contextlib.nullcontext()):
                        sp, up = system_prompt, user_prompt
                        if current_p == "lm_studio":
                            sp, ms = self._lm_studio_fit(model, sp, [{"role": "user", "content": up}])
                            up = ms[-1]["content"]

                        def send():
                            return self._with_local_json_mode(require_json, lambda json_mode: self._call_local(
                                url, model, sp, up, temp,
                                reasoning_effort=self._local_reasoning_effort(current_p),
                                timeout=self._local_timeout(), require_json=json_mode,
                                max_tokens=local_max_output_tokens()))

                        try:
                            return send()
                        except Exception as e:  # noqa: BLE001
                            if current_p == "lm_studio" and self._grow_lm_studio_context(model, e):
                                return send()
                            raise

                try:
                    logger.info(f"Attempting generation via local {current_p} at {url} (model: {model})...")
                    return call_local()
                except ContextTooLarge as e:
                    logger.warning(f"{current_p} API call failed: {e}.")
                    too_large = e
                except Exception as e:
                    logger.warning(f"{current_p} API call failed: {e}.")


        # Every provider failed or none was configured.
        if too_large is not None:
            raise too_large
        if not _simulation_enabled():
            msg = (
                "No local LLM provider is reachable (LM Studio / Ollama / llama.cpp). "
                "Cloud providers are blocked by Strict Local Mode to ensure zero data leaves your PC."
                if self.config.get("local_only", True)
                else "No LLM provider is reachable. Check your API keys and that the selected model is available in Settings."
            )
            raise LLMUnavailable(msg)

        # The canned response below is NOT model output -- flag it so callers
        # can label it. See backend/dev/fixtures.py.
        logger.warning(
            "No LLM provider succeeded; returning simulated content. "
            "Check API keys and provider availability in Settings."
        )
        self.last_response_simulated = True
        self.last_provider = None
        from dev.fixtures import generate_simulated_response
        return generate_simulated_response(system_prompt, user_prompt, require_json)

    def _call_openai(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        model = model_name or self.config.get("openai_model", "gpt-4o-mini")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }

        if require_json:
            payload["response_format"] = {"type": "json_object"}
            
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API returned code {response.status_code}: {response.text}")
            
        resp_json = response.json()
        try:
            text = resp_json["choices"][0]["message"]["content"]
            return text
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse OpenAI response payload: {resp_json}. Error: {e}")

    def _call_gemini(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        configured_model = model_name or self.config.get("gemini_model", "gemini-1.5-flash")
        candidate_models = [configured_model, "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
        # Remove duplicates preserving order
        candidate_models = list(dict.fromkeys(candidate_models))
        
        headers = {
            "Content-Type": "application/json"
        }
        
        last_error = None
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [{"text": user_prompt}]
                    }
                ]
            }
            if system_prompt:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_prompt}]
                }
            generation_config = {"temperature": temperature}
            if require_json:
                generation_config["responseMimeType"] = "application/json"
            payload["generationConfig"] = generation_config
            
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=45)
                if response.status_code == 200:
                    resp_json = response.json()
                    text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                    return text
                else:
                    last_error = f"Gemini API ({model}) returned code {response.status_code}: {response.text[:200]}"
                    logger.warning(last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Error calling Gemini model {model}: {e}")
                
        raise Exception(f"All Gemini models failed. Last error: {last_error}")

    def _call_gemini_harness(
        self,
        endpoint_url: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        require_json: bool,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: int = GEMINI_TIMEOUT_SECONDS,
        effort: Optional[str] = None,
    ) -> str:
        full_input = f"{system_prompt}\n\n{user_prompt}".strip() if system_prompt else user_prompt
        alias = (model or "").strip()
        if not alias or alias.lower() in ("gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash"):
            alias = "flash"
        elif alias.lower() in ("gemini-1.5-pro", "gemini-2.0-pro", "gemini-pro"):
            alias = "pro"

        chosen_effort = self.gemini_effort_level(effort)
        if (alias == "flash" or "flash" in (model or "").lower()) and chosen_effort == "max":
            chosen_effort = "high"

        payload = {
            "model": alias or "flash",
            "input": full_input,
            "thinking_level": chosen_effort,
            "output_format": "json" if require_json else "text",
        }

        url = endpoint_url.rstrip("/")
        if not url.endswith("/api/gemini"):
            url = f"{url}/api/gemini"

        _harness_gate()
        response = requests.post(url, json=payload, timeout=timeout)
        if response.status_code == 429:
            _harness_rate_limited(response)
        if response.status_code != 200:
            raise Exception(f"Gemini harness ({url}) returned code {response.status_code}: {response.text[:300]}")

        from integrations import gemini_limit
        gemini_limit.clear()
        resp_json = response.json()
        output = resp_json.get("output")
        if isinstance(output, dict):
            status = output.get("status")
            if status and status != "SUCCESS":
                err = output.get("error") or output.get("message") or status
                raise Exception(f"Gemini harness execution error: {err}")
            text = output.get("response") or ""
        elif isinstance(output, str):
            text = output
        else:
            text = str(output or "")

        if require_json:
            text = clean_json_response(text)
        return _non_empty_reply(text, model)

    def _chat_gemini_harness(
        self,
        endpoint_url: str,
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: int = GEMINI_TIMEOUT_SECONDS,
        effort: Optional[str] = None,
    ) -> str:
        parts = []
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        for m in messages:
            role = "User" if m.get("role") == "user" else "Assistant"
            parts.append(f"{role}: {m.get('content', '')}")
        full_input = "\n\n".join(parts)

        alias = (model or "").strip()
        if not alias or alias.lower() in ("gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash"):
            alias = "flash"
        elif alias.lower() in ("gemini-1.5-pro", "gemini-2.0-pro", "gemini-pro"):
            alias = "pro"

        chosen_effort = self.gemini_effort_level(effort)
        if (alias == "flash" or "flash" in (model or "").lower()) and chosen_effort == "max":
            chosen_effort = "high"

        payload = {
            "model": alias or "flash",
            "input": full_input,
            "thinking_level": chosen_effort,
            "output_format": "json" if require_json else "text",
        }

        url = endpoint_url.rstrip("/")
        if not url.endswith("/api/gemini"):
            url = f"{url}/api/gemini"

        _harness_gate()
        response = requests.post(url, json=payload, timeout=timeout)
        if response.status_code == 429:
            _harness_rate_limited(response)
        if response.status_code != 200:
            raise Exception(f"Gemini harness ({url}) returned code {response.status_code}: {response.text[:300]}")

        from integrations import gemini_limit
        gemini_limit.clear()
        resp_json = response.json()
        output = resp_json.get("output")
        if isinstance(output, dict):
            status = output.get("status")
            if status and status != "SUCCESS":
                err = output.get("error") or output.get("message") or status
                raise Exception(f"Gemini harness execution error: {err}")
            text = output.get("response") or ""
        elif isinstance(output, str):
            text = output
        else:
            text = str(output or "")

        if require_json:
            text = clean_json_response(text)
        return _non_empty_reply(text, model)

    def thinking_enabled(self) -> bool:
        """Settings -> Thinking: `thinking_agents` (default on) for agents
        and writing; `thinking_production` (default off) for video
        production's visual planning; `thinking_chat` (default off) for
        interactive chat and Studio Director -- chat requires immediate replies
        and must not be blocked by 7-minute reasoning loops that exceed HTTP
        timeouts."""
        if self.purpose == "production":
            return bool(self.config.get("thinking_production", False))
        if self.purpose in ("chat", "director_chat"):
            return bool(self.config.get("thinking_chat", False))
        return bool(self.config.get("thinking_agents", True))

    @staticmethod
    def _with_local_json_mode(require_json: bool, call):
        """Run `call(json_mode)` with JSON mode when the caller requires JSON.
        A local server that rejects `response_format` (an older build, a
        model without a JSON grammar) answers 4xx; the call is then made once
        more without it, so JSON mode can only help, never strand a call."""
        if not require_json:
            return call(False)
        try:
            return call(True)
        except Exception as e:  # noqa: BLE001 - only a client-side refusal is retried
            if not re.search(r"returned code 4\d\d", str(e)):
                raise
            logger.info("Local server refused JSON mode (%s); retrying without it.", str(e)[:120])
            return call(False)

    def _local_reasoning_effort(self, provider: str) -> Optional[str]:
        """`"none"` turns a thinking model's reasoning off in LM Studio; with
        thinking on nothing is sent and the model reasons as it normally does.
        Other local servers get nothing either way."""
        if provider != "lm_studio" or self.thinking_enabled():
            return None
        return "none"

    def _local_timeout(self) -> int:
        """A thinking model answers in minutes, not seconds."""
        return 600 if self.thinking_enabled() else 180

    def _call_local(
        self,
        base_url: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        reasoning_effort: Optional[str] = None,
        timeout: int = 180,
        require_json: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """LM Studio, Ollama and llama.cpp all speak the OpenAI chat API.
        `require_json` asks the server for JSON mode: a small local model
        (Gemma 4 e4b on Ollama) otherwise answers a "reply with one JSON
        object" task with prose, a script or a Markdown plan."""
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if require_json:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)

        response = requests.post(url, headers=headers, json=payload, timeout=timeout)

        if response.status_code != 200:
            raise Exception(f"{url} returned code {response.status_code}: {response.text[:300]}")

        resp_json = response.json()
        _CALL.usage = resp_json.get("usage") if isinstance(resp_json.get("usage"), dict) else None
        try:
            msg = resp_json["choices"][0]["message"]
            text = msg.get("content") or msg.get("reasoning_content") or ""
            return _non_empty_reply(text, model)
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse local model response payload: {resp_json}. Error: {e}")

def _non_empty_reply(text: Any, model: str) -> str:
    """A model that answers with nothing (a reasoning model that spent its whole
    budget thinking, a stalled server) has failed the call: an empty string
    must never be saved as a finished step. Raising lets the normal provider
    fallback and the callers' retries take over."""
    if not str(text or "").strip():
        raise Exception(f"'{model}' returned an empty reply")
    return str(text)


def clean_json_response(raw_text: str) -> str:
    """Helper to remove markdown code blocks wrapping JSON."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Find first newline
        lines = cleaned.splitlines()
        if lines[0].startswith("```json") or lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned

llm_service = LLMService()

