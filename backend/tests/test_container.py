
from core.container import ServiceContainer

def test_register():
    c = ServiceContainer()
    c.register("a", 123)
    assert c.resolve("a") == 123
