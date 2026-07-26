import os
import re
import logging
from typing import Dict, Any, List, Optional
from core.markdown import markdown_loader

logger = logging.getLogger("spilled_coffee_ai.core.prompt")

PROMPTS_DIR = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\prompts"

REQUIRED_SECTIONS = ["role", "objective", "instructions", "output_format"]

class PromptTemplate:
    def __init__(self, raw_content: str, metadata: Dict[str, Any]):
        self.raw_content = raw_content
        self.metadata = metadata
        self.sections: Dict[str, str] = {}
        self.parse_sections()

    def parse_sections(self):
        # Clean and split content by sections
        content = self.raw_content.strip()
        pattern = r"^(#{1,3})\s+(.*?)$"
        parts = re.split(pattern, content, flags=re.MULTILINE)
        
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

    def validate_sections(self):
        """Validate required prompt sections (Role, Objective, Instructions, Output Format)."""
        # System instructions or parent guides might omit examples, but must have core sections
        for sec in REQUIRED_SECTIONS:
            if sec not in self.sections and "body" not in self.sections:
                raise ValueError(f"Prompt validation error: Required section '{sec.replace('_', ' ').title()}' is missing in the prompt template.")

    def render(self, **kwargs) -> str:
        """Substitute placeholders and validate they are all resolved."""
        # Join sections back or render raw content
        rendered = self.raw_content
        
        # Discover all placeholders of format {placeholder_name}
        placeholders = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", rendered))
        
        missing = [p for p in placeholders if p not in kwargs]
        if missing:
            raise ValueError(f"Prompt rendering error: Missing required rendering variables: {missing}")
            
        for k, v in kwargs.items():
            rendered = rendered.replace(f"{{{k}}}", str(v))
            
        return rendered

class PromptManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptManager, cls).__new__(cls)
            cls._instance.templates: Dict[str, PromptTemplate] = {}
        return cls._instance

    def load_prompt(self, relative_path: str) -> PromptTemplate:
        """Loads prompt, resolving inheritance automatically."""
        abs_path = os.path.abspath(os.path.join(PROMPTS_DIR, relative_path))
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Prompt template file not found at: {abs_path}")
            
        doc = markdown_loader.load(abs_path)
        fm = doc.frontmatter
        
        # 1. Parse prompt inheritance (PromptInheritance.md)
        parent_content = ""
        extends_rel = fm.get("extends")
        if extends_rel:
            logger.info(f"PromptManager: Prompt '{relative_path}' extends '{extends_rel}' - merging parent prompts.")
            parent_template = self.load_prompt(extends_rel)
            parent_content = parent_template.raw_content + "\n\n"
            
        # Merge contents
        merged_content = parent_content + doc.raw_content
        
        template = PromptTemplate(merged_content, {
            "id": doc.metadata["id"],
            "path": abs_path,
            "version": fm.get("version", "1.0.0"),
            "category": fm.get("category", "prompt")
        })
        
        # Validate required sections (PromptValidation.md)
        template.validate_sections()
        
        self.templates[relative_path] = template
        return template

    def get_template(self, relative_path: str) -> PromptTemplate:
        if relative_path in self.templates:
            return self.templates[relative_path]
        return self.load_prompt(relative_path)

prompt_manager = PromptManager()
