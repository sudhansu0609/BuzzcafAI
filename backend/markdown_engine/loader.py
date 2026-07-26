
from pathlib import Path

class MarkdownLoader:
    def load(self, path:str)->str:
        return Path(path).read_text(encoding="utf-8")
