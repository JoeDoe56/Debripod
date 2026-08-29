__all__ = ["create_app"]


async def create_app():
    from .app import create_app as factory
    return await factory()
