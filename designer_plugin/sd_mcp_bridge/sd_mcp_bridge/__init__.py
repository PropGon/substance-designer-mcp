"""Puente MCP para Substance 3D Designer."""

_bridge = None


def initializeSDPlugin() -> None:
    # Imported here so transport.py stays importable (and testable) outside Designer.
    from .plugin import Bridge

    global _bridge
    _bridge = Bridge()
    _bridge.start()


def uninitializeSDPlugin() -> None:
    global _bridge
    if _bridge is not None:
        _bridge.stop()
        _bridge = None
