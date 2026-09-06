import os
import json
import logging
import uuid
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from core.config import config_manager

logger = logging.getLogger("buzzcaf_ai.memory")

class MemoryItem:
    def __init__(self, scope: str, owner: str, tags: List[str], content: Any, confidence: float = 1.0, source: str = "agent", id: Optional[str] = None):
        self.id = id or str(uuid.uuid4())
        self.scope = scope  # global, department, agent, project, session
        self.owner = owner  # agent role name or "system"
        self.tags = tags
        self.content = content
        self.confidence = confidence
        self.source = source
        self.created = datetime.now().isoformat()
        self.updated = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "owner": self.owner,
            "tags": self.tags,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
            "created": self.created,
            "updated": self.updated
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryItem":
        item = cls(
            scope=d["scope"],
            owner=d["owner"],
            tags=d["tags"],
            content=d["content"],
            confidence=d.get("confidence", 1.0),
            source=d.get("source", "agent"),
            id=d["id"]
        )
        item.created = d.get("created", item.created)
        item.updated = d.get("updated", item.updated)
        return item

class MemorySystem:
    def __init__(self):
        self.session_memory: Dict[str, List[MemoryItem]] = {}  # In-memory volatile session layers

    def _get_storage_path(self, scope: str, owner: str = "system", project_id: Optional[str] = None) -> Optional[str]:
        knowledge_path = config_manager.get("KNOWLEDGE_PATH")
        projects_path = config_manager.get("PROJECTS_PATH")
        
        owner_clean = (owner or "system").lower().replace(" ", "_").replace(":", "")
        if scope == "global":
            return os.path.join(knowledge_path, "global_memory.json")
        elif scope == "department":
            return os.path.join(knowledge_path, f"dept_{owner_clean}_memory.json")
        elif scope == "agent":
            return os.path.join(knowledge_path, f"agent_{owner_clean}_memory.json")
        elif scope == "session":
            return os.path.join(knowledge_path, f"session_{owner_clean}_memory.json")
        elif scope == "project" and project_id:
            return os.path.join(projects_path, project_id, "project_memory.json")
        return os.path.join(knowledge_path, f"memory_{scope}_{owner_clean}.json")

    _SCOPE_PREFIXES = {
        "department": "dept_",
        "agent": "agent_",
        "session": "session_",
    }

    def _get_scope_paths(self, scope: str, project_id: Optional[str] = None) -> List[str]:
        """Every storage file belonging to a scope, across all owners.

        Memory is stored one file per (scope, owner). Callers that omit an
        owner mean "the whole scope", so resolve to every matching file
        rather than silently reading the 'system' owner's file only.
        """
        knowledge_path = config_manager.get("KNOWLEDGE_PATH")
        if scope == "global":
            return [os.path.join(knowledge_path, "global_memory.json")]
        if scope == "project":
            path = self._get_storage_path(scope, "system", project_id)
            return [path] if path else []

        prefix = self._SCOPE_PREFIXES.get(scope, f"memory_{scope}_")
        if not os.path.isdir(knowledge_path):
            return []
        return [
            os.path.join(knowledge_path, name)
            for name in sorted(os.listdir(knowledge_path))
            if name.startswith(prefix) and name.endswith("_memory.json")
        ]

    def _load_memories(self, path: str) -> List[MemoryItem]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [MemoryItem.from_dict(d) for d in data]
        except Exception as e:
            # Corrupt memory must not take the agent down, but it should be
            # visible -- a silent [] looks identical to "no memories yet".
            logger.warning(f"Could not read memories from {path}: {e}")
            return []

    def _save_memories(self, path: str, items: List[MemoryItem]) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([item.to_dict() for item in items], f, indent=2)
        except Exception as e:
            # Swallowing this silently hid the fact that memory was being
            # written to a directory that did not exist.
            logger.error(f"Failed to persist memories to {path}: {e}")

    def save(self, scope: str, owner: str, tags: List[str], content: Any, confidence: float = 1.0, project_id: Optional[str] = None) -> MemoryItem:
        """Saves a structured memory item to persistent disk storage, preventing duplicates."""
        item = MemoryItem(scope=scope, owner=owner, tags=tags, content=content, confidence=confidence)
        
        path = self._get_storage_path(scope, owner, project_id)
        if path:
            items = self._load_memories(path)
            # Deduplicate write checks
            for existing in items:
                if existing.content == content:
                    existing.updated = datetime.now().isoformat()
                    self._save_memories(path, items)
                    return existing
            items.append(item)
            self._save_memories(path, items)
            
        return item

    _STOPWORDS = frozenset(
        "a an the this that these those my your our their its is are was were be been "
        "am do does did have has had will would shall should can could may might must "
        "of in on at to for with from by about into over and or but if then when what "
        "which who where why how there here please ok okay hey me we us you he she it "
        "they them i".split()
    )

    @classmethod
    def _tokens(cls, text: str) -> set:
        import re as _re

        return {
            tok for tok in _re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(tok) > 2 and tok not in cls._STOPWORDS
        }

    def retrieve(self, scope: str, owner: Optional[str] = None, tags: Optional[List[str]] = None, project_id: Optional[str] = None, limit: int = 15, query: Optional[str] = None) -> List[MemoryItem]:
        """Retrieves memory entries by scope, optional tags and recency.

        With `query`, items are ranked by how many content words they share
        with the query (recency breaks ties) so the message decides what is
        recalled; without matches, or without a query, newest first. With no
        owner, returns memories for every owner in the scope.
        """
        items: List[MemoryItem] = []

        if owner:
            path = self._get_storage_path(scope, owner, project_id)
            if path:
                items = self._load_memories(path)
        else:
            for path in self._get_scope_paths(scope, project_id):
                items.extend(self._load_memories(path))

        # Filter by tags list intersection
        if tags:
            filtered: List[MemoryItem] = []
            for item in items:
                # If there's any tag overlap
                if any(t in item.tags for t in tags):
                    filtered.append(item)
            items = filtered

        # Sort by updated timestamp desc (recency)
        items.sort(key=lambda x: x.updated, reverse=True)

        query_tokens = self._tokens(query) if query else set()
        if query_tokens:
            scored = []
            for item in items:
                text = json.dumps(item.content) if isinstance(item.content, (dict, list)) else str(item.content)
                overlap = len(query_tokens & self._tokens(text))
                scored.append((overlap, item))
            if any(score > 0 for score, _ in scored):
                # Stable sort keeps the recency order among equal scores.
                scored.sort(key=lambda pair: pair[0], reverse=True)
                return [item for score, item in scored if score > 0][:limit]
        return items[:limit]

    def clear(self, scope: str, owner: Optional[str] = None, project_id: Optional[str] = None) -> None:
        """Clears memory storage. With no owner, clears the whole scope."""
        if owner:
            targets = [self._get_storage_path(scope, owner, project_id)]
        else:
            targets = self._get_scope_paths(scope, project_id)

        for path in targets:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning(f"Could not clear memory file {path}: {e}")

memory_system = MemorySystem()
