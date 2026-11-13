"""Puente MCP para Substance 3D Designer."""

_bridge = None
_ui = None
_log_handler = None


def initializeSDPlugin() -> None:
    # Imported here so the stdlib modules stay importable (and testable) outside Designer.
    import logging

    import sd

    from . import transport
    from .plugin import Bridge, logger

    global _bridge, _ui, _log_handler
    _log_handler = sd.getContext().createRuntimeLogHandler()
    logger.addHandler(_log_handler)
    logger.setLevel(logging.INFO)

    _bridge = Bridge()
    try:
        autostart = transport.autostart_enabled()
    except (OSError, ValueError) as exc:
        logger.error("config.json no es valido (%s); el puente se activa igualmente.", exc)
        autostart = True
    if autostart:
        _bridge.start()
    else:
        logger.info("Puente MCP desactivado al iniciar; activalo desde el menu MCP.")

    try:
        from .ui import BridgeUi

        _ui = BridgeUi(_bridge)
    except Exception as exc:
        # The bridge must keep working even if this Designer version lacks some UI API.
        logger.warning("No se pudo crear el menu MCP: %s", exc)


def uninitializeSDPlugin() -> None:
    global _bridge, _ui, _log_handler
    if _ui is not None:
        _ui.dispose()
        _ui = None
    if _bridge is not None:
        _bridge.stop()
        _bridge = None
    if _log_handler is not None:
        from .plugin import logger

        logger.removeHandler(_log_handler)
        _log_handler = None
