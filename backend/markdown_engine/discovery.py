
from pathlib import Path

def discover(root):
    return list(Path(root).rglob("*.md"))
