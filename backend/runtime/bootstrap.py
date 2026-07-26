
from config.settings import Settings
from core.container import ServiceContainer

def bootstrap():
    settings = Settings()
    container = ServiceContainer()
    container.register("settings", settings)
    return container
