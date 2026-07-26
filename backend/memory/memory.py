import os
import json
import uuid
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from core.config import config_manager

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

    def _load_memories(self, path: str) -> List[MemoryItem]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [MemoryItem.from_dict(d) for d in data]
        except Exception:
            return []

    def _save_memories(self, path: str, items: List[MemoryItem]) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([item.to_dict() for item in items], f, indent=2)
        except Exception:
            pass

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

    def retrieve(self, scope: str, owner: str = "system", tags: Optional[List[str]] = None, project_id: Optional[str] = None, limit: int = 15) -> List[MemoryItem]:
        """Retrieves and filters memory entries by tag matching, scope, and recency."""
        items: List[MemoryItem] = []
        
        path = self._get_storage_path(scope, owner, project_id)
        if path:
            items = self._load_memories(path)

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
        return items[:limit]

    def clear(self, scope: str, owner: str = "system", project_id: Optional[str] = None) -> None:
        """Clears memory storage layer file."""
        path = self._get_storage_path(scope, owner, project_id)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

memory_system = MemorySystem()
