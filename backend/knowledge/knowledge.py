import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("spilled_coffee_ai.core.knowledge")

KNOWLEDGE_DIR = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\knowledge"
INDEX_PATH = os.path.join(KNOWLEDGE_DIR, "index.json")

CATEGORIES = ["research", "prompts", "assets", "stories"]

class KnowledgeManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KnowledgeManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
        self.index: List[Dict[str, Any]] = []
        self.setup_directories()
        self.load_index()
        self.initialized = True

    def setup_directories(self):
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        for cat in CATEGORIES:
            os.makedirs(os.path.join(KNOWLEDGE_DIR, cat), exist_ok=True)

    def load_index(self):
        if os.path.exists(INDEX_PATH):
            try:
                with open(INDEX_PATH, "r", encoding="utf-8") as f:
                    self.index = json.load(f)
                self.validate_index()
            except Exception as e:
                logger.error(f"KnowledgeManager: Error loading index file: {e}")
                self.rebuild_index()
        else:
            self.rebuild_index()

    def save_index(self):
        try:
            with open(INDEX_PATH, "w", encoding="utf-8") as f:
                json.dump(self.index, f, indent=4)
        except Exception as e:
            logger.error(f"KnowledgeManager: Error saving index: {e}")

    def validate_index(self):
        """Verify indexed documents actually exist, purge missing items, reload modified ones."""
        valid_items = []
        changed = False
        for item in self.index:
            path = item.get("filepath", "")
            if path and os.path.exists(path):
                # Verify mod time
                current_mtime = os.path.getmtime(path)
                if current_mtime != item.get("last_modified", 0.0):
                    # File changed, reload summary/tags
                    item["last_modified"] = current_mtime
                    changed = True
                valid_items.append(item)
            else:
                # File deleted, purge from index
                changed = True
                
        self.index = valid_items
        if changed:
            self.save_index()

    def rebuild_index(self):
        """Scan directory structure to fully rebuild the index."""
        logger.info("KnowledgeManager: Rebuilding knowledge base index...")
        self.index.clear()
        self.setup_directories()
        
        for cat in CATEGORIES:
            cat_dir = os.path.join(KNOWLEDGE_DIR, cat)
            for f_name in os.listdir(cat_dir):
                if f_name.endswith(".md") or f_name.endswith(".json") or f_name.endswith(".txt"):
                    f_path = os.path.join(cat_dir, f_name)
                    doc_id = os.path.splitext(f_name)[0]
                    
                    # Extract quick metadata from content
                    tags = [cat, doc_id]
                    summary = f"Shared knowledge file in category {cat}."
                    
                    try:
                        if f_name.endswith(".json"):
                            with open(f_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            tags.extend(data.get("tags", []))
                            summary = data.get("description", summary)
                    except Exception:
                        pass
                        
                    self.index.append({
                        "id": doc_id,
                        "category": cat,
                        "title": doc_id.replace("_", " ").title(),
                        "tags": list(set([t.lower().strip() for t in tags])),
                        "filepath": f_path,
                        "summary": summary,
                        "last_modified": os.path.getmtime(f_path)
                    })
        self.save_index()

    def save_document(self, category: str, doc_id: str, title: str, content: str, tags: List[str], summary: str = ""):
        """Create or update a document in the knowledge base."""
        if category not in CATEGORIES:
            raise ValueError(f"Invalid knowledge category: {category}. Must be one of {CATEGORIES}")
            
        ext = "md"
        if content.strip().startswith("{") and content.strip().endswith("}"):
            ext = "json"
            
        f_name = f"{doc_id}.{ext}"
        f_path = os.path.join(KNOWLEDGE_DIR, category, f_name)
        
        # Save content file
        with open(f_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        # Update index
        existing = next((item for item in self.index if item["id"] == doc_id and item["category"] == category), None)
        item_tags = list(set([t.lower().strip() for t in tags + [category, doc_id]]))
        
        item_data = {
            "id": doc_id,
            "category": category,
            "title": title,
            "tags": item_tags,
            "filepath": f_path,
            "summary": summary or f"Shared knowledge file in category {category}.",
            "last_modified": os.path.getmtime(f_path)
        }
        
        if existing:
            self.index.remove(existing)
            
        self.index.append(item_data)
        self.save_index()
        logger.info(f"KnowledgeManager: Saved and indexed knowledge document '{doc_id}' in category '{category}'")

    def search(self, query: str = "", category: Optional[str] = None, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """Provides metadata filtering and keyword search."""
        self.validate_index()
        results = self.index
        
        # Category Filter
        if category:
            results = [r for r in results if r["category"].lower() == category.lower()]
            
        # Tag Filter
        if tag:
            results = [r for r in results if tag.lower() in [t.lower() for t in r["tags"]]]
            
        # Keyword query match
        if query:
            q_clean = query.lower().strip()
            matched = []
            for r in results:
                # Check match in title, tags, or summary
                if q_clean in r["title"].lower() or q_clean in r["summary"].lower() or any(q_clean in t.lower() for t in r["tags"]):
                    matched.append(r)
                    continue
                # Check match inside raw text content file
                try:
                    with open(r["filepath"], "r", encoding="utf-8") as f:
                        text = f.read().lower()
                    if q_clean in text:
                        matched.append(r)
                except Exception:
                    pass
            results = matched
            
        return results

knowledge_manager = KnowledgeManager()
