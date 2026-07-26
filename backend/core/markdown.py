import os
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("spilled_coffee_ai.core.markdown")

class MarkdownDocument:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.raw_content = ""
        self.frontmatter: Dict[str, Any] = {}
        self.sections: Dict[str, str] = {}
        self.metadata: Dict[str, Any] = {}
        self.mtime = 0.0
        self.parse()

    def parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Markdown document not found at: {self.file_path}")
            
        self.mtime = os.path.getmtime(self.file_path)
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.raw_content = f.read()

        content = self.raw_content.strip()
        
        # 1. Parse Frontmatter if present
        # Delimited by lines starting with '---'
        if content.startswith("---"):
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
            if match:
                yaml_text = match.group(1)
                body = match.group(2)
                # Simple parser since we don't have PyYAML loaded
                for line in yaml_text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        self.frontmatter[k.strip().lower()] = v.strip().strip('"').strip("'")
                content = body.strip()

        # 2. Parse Heading Sections
        # Split content by # or ## headings
        pattern = r"^(#{1,3})\s+(.*?)$"
        parts = re.split(pattern, content, flags=re.MULTILINE)
        
        # Split results: [text_before_headings, heading_level, heading_title, text_after_heading, ...]
        if len(parts) > 1:
            self.sections["introduction"] = parts[0].strip()
            i = 1
            while i < len(parts):
                level = parts[i]
                title = parts[i+1].strip().lower().replace(" ", "_")
                body = parts[i+2].strip()
                self.sections[title] = body
                i += 3
        else:
            self.sections["body"] = content

        # Metadata standards
        self.metadata = {
            "id": os.path.splitext(os.path.basename(self.file_path))[0],
            "path": self.file_path,
            "version": self.frontmatter.get("version", "1.0.0"),
            "category": self.frontmatter.get("category", "specification"),
            "last_modified": self.mtime
        }

class MarkdownLoader:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MarkdownLoader, cls).__new__(cls)
            cls._instance.cache = {}
            cls._instance.registry = []
        return cls._instance

    def load(self, file_path: str) -> MarkdownDocument:
        abs_path = os.path.abspath(file_path)
        
        # Cache Validation check on mtime
        if abs_path in self.cache:
            doc = self.cache[abs_path]
            if os.path.exists(abs_path) and os.path.getmtime(abs_path) == doc.mtime:
                return doc
            else:
                logger.info(f"Invalidating cache for: {abs_path} (file modified on disk).")
                self.invalidate_cache(abs_path)

        doc = MarkdownDocument(abs_path)
        self.cache[abs_path] = doc
        
        # Track in Document Registry
        if abs_path not in [r["path"] for r in self.registry]:
            self.registry.append(doc.metadata)
            
        return doc

    def load_all(self, directory: str) -> List[MarkdownDocument]:
        docs = []
        if not os.path.exists(directory):
            return docs
            
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".md"):
                    path = os.path.join(root, file)
                    try:
                        docs.append(self.load(path))
                    except Exception as e:
                        logger.error(f"Error loading document {path}: {e}")
        return docs

    def reload(self, file_path: str) -> MarkdownDocument:
        self.invalidate_cache(file_path)
        return self.load(file_path)

    def invalidate_cache(self, file_path: str):
        abs_path = os.path.abspath(file_path)
        if abs_path in self.cache:
            del self.cache[abs_path]
            # Remove from registry
            self.registry = [r for r in self.registry if r["path"] != abs_path]

markdown_loader = MarkdownLoader()
