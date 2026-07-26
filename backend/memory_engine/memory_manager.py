from memory.memory import memory_system

class MemoryManager:
    """Delegates to central MemorySystem."""
    def __init__(self):
        self.system = memory_system

    def write(self, scope: str, tags: list[str], content: dict, key_field: str = "id"):
        return self.system.write_memory(scope, tags, content, key_field)

    def retrieve(self, scope: str, tag_filter: list[str] = None, limit: int = 10):
        return self.system.retrieve_memories(scope, tag_filter, limit)
