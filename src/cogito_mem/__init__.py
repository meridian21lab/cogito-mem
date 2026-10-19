"""cogito-mem: a fast, simple, local memory for agents.

    from cogito_mem import Memory
    mem = Memory()                      # ~/.cogito-mem, EmbeddingGemma 2 via llama.cpp
    mem.handle({"op": "append", "items": [{"author": "user", "text": "..."}]})
    mem.handle({"op": "query", "text": "..."})

``Client`` sends the same dictionaries to the local service instead.
"""

__version__ = "0.1.0"

__all__ = ["Memory", "Config", "Client", "ApiError", "__version__"]


def __getattr__(name):  # keep `import cogito_mem` light for hooks and the MCP bridge
    if name in ("Memory", "Config"):
        from . import memory

        return getattr(memory, name)
    if name == "Client":
        from .client import Client

        return Client
    if name == "ApiError":
        from .errors import ApiError

        return ApiError
    raise AttributeError(name)
