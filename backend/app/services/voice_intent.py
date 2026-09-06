"""Keyword tables for voice command routing -- the single backend definition.

There used to be two of these in app/main.py (`/api/voice/parse_intent` and
`/api/jarvis/voice`) with different keywords for the same channels, so a phrase
could route one way through one endpoint and another way through the other.
The unused endpoint is gone; this module is what remains.

The frontend keeps a deliberately smaller copy of these keywords in App.tsx as
an *offline* fallback, used only when this API is unreachable. That one is
intentional duplication -- if you add a keyword here that matters offline, add
it there too.

Order matters: the first matching entry wins, so put the more specific phrase
("spilled coffee after dark") before the generic one ("studio").
"""
from typing import Dict, List, Optional

# Phrase fragment -> canonical channel name.
CHANNEL_KEYWORDS: List[tuple] = [
    (["after dark", "spilled coffee after dark", "horror", "raat", "ghost"], "Spilled Coffee After Dark"),
    (["spilled coffee studio", "studio", "original", "story"], "Spilled Coffee Studio"),
    (["beyond3baje", "beyond", "documentary", "true story", "crime"], "Beyond3Baje"),
    (["life3baje", "life", "essay", "vlog", "journey"], "Life3Baje"),
    (["khayal3baje", "khayal", "mythology", "lore", "ancient"], "Khayal3Baje"),
]

# Phrase fragment -> UI tab id.
TAB_KEYWORDS: List[tuple] = [
    (["project", "projects", "catalog", "production catalog"], "projects"),
    (["topic", "topics", "vault", "discover", "discovery", "idea", "ideas"], "topic_discovery"),
    (["research", "citation", "citations", "source", "sources", "study"], "research"),
    (["writing", "script", "scripts", "editor", "write"], "writing"),
    (["production", "scene", "board", "filmora", "b-roll", "b roll"], "production"),
    (["publish", "publishing", "analytic", "analytics", "performance", "view", "views", "stat", "stats"], "publishing"),
    (["workforce", "agent", "agents", "bot", "bots", "registry"], "ai_workforce"),
    (["health", "diagnostic", "diagnostics", "status", "system"], "health"),
    (["setting", "settings", "router", "config", "parameters", "api key"], "settings"),
    (["dashboard", "home", "overview", "main"], "dashboard"),
]

# Action flag name -> phrase fragments that trigger it.
ACTION_KEYWORDS: Dict[str, List[str]] = {
    "is_save": ["save", "bookmark", "add to vault"],
    "is_chat": ["chat", "talk", "discuss", "strategist", "ask agent"],
    "is_discover": ["find", "search", "discover", "generate", "look up", "sweep"],
    "is_stop": ["stop", "quiet", "mute", "turn off", "sleep", "pause"],
    "is_log": ["activity log", "show log", "open log", "history", "logs", "activity"],
}


def _first_match(phrase: str, table: List[tuple]) -> Optional[str]:
    for keywords, value in table:
        if any(kw in phrase for kw in keywords):
            return value
    return None


def resolve_channel(phrase: str) -> Optional[str]:
    return _first_match(phrase.lower(), CHANNEL_KEYWORDS)


def resolve_tab(phrase: str) -> Optional[str]:
    return _first_match(phrase.lower(), TAB_KEYWORDS)


def resolve_actions(phrase: str) -> Dict[str, bool]:
    lowered = phrase.lower()
    return {
        flag: any(kw in lowered for kw in keywords)
        for flag, keywords in ACTION_KEYWORDS.items()
    }
