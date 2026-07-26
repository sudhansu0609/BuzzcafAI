import yaml
import re

class FrontMatterParser:
    """YAML front matter parser using standard library or PyYAML."""

    def parse(self, text: str):
        # Match frontmatter using regex
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            fm_text = match.group(1)
            body_text = text[match.end():]
            try:
                metadata = yaml.safe_load(fm_text) or {}
                return metadata, body_text
            except Exception:
                return {}, body_text
        return {}, text
