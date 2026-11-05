"""Qt side of the bridge. Runs only inside Designer.

Follows Designer's documented threading pattern: the socket lives in a QThread and
hands each command to a QObject on the main thread through a queued signal, because
the ``sd`` API may only be called from the main application thread.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

import sd
from PySide6 import QtCore

from . import handlers, transport

COMMAND_TIMEOUT_SECONDS = 120.0

logger = logging.getLogger("sd_mcp_bridge")


class _Call:
    def __init__(self, command: str, params: dict):
        self.command = command
        self.params = params
        self.future: Future = Future()


class MainThreadExecutor(QtCore.QObject):
    _requested = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self._requested.connect(self._run, QtCore.Qt.QueuedConnection)

    def call(self, command: str, params: dict):
        """Called from the socket thread; blocks it until the main thread answers."""
        call = _Call(command, params)
        self._requested.emit(call)
        try:
            return call.future.result(timeout=COMMAND_TIMEOUT_SECONDS)
        except FutureTimeout:
            raise transport.BridgeError(
                "timeout",
                "Designer no respondio a tiempo. Puede estar calculando o tener un dialogo abierto; "
                "el comando podria ejecutarse igualmente cuando se libere.",
            ) from None

    @QtCore.Slot(object)
    def _run(self, call: _Call) -> None:
        # BaseException on purpose: sd's APIException derives from it, and a slot that lets
        # one escape would leave the socket thread waiting for an answer that never comes.
        try:
            call.future.set_result(handlers.execute(call.command, call.params))
        except transport.BridgeError as exc:
            call.future.set_exception(exc)
        except BaseException as exc:
            call.future.set_exception(transport.BridgeError("internal", f"{type(exc).__name__}: {exc}"))


class _TransportThread(QtCore.QThread):
    def __init__(self, server: transport.BridgeTransport):
        super().__init__()
        self._server = server

    def run(self) -> None:
        self._server.serve_forever()


class Bridge:
    def __init__(self):
        self._token = transport.new_token()
        self._executor = None
        self._server = None
        self._thread = None
        self._log_handler = None

    def start(self) -> None:
        self._log_handler = sd.getContext().createRuntimeLogHandler()
        logger.addHandler(self._log_handler)
        logger.setLevel(logging.INFO)

        self._executor = MainThreadExecutor()
        try:
            port = transport.configured_port()
            server = transport.BridgeTransport(self._token, self._executor.call, port)
            server.bind()
        except (OSError, ValueError) as exc:
            logger.error("sd_mcp_bridge no pudo iniciar el puente: %s. Revisa config.json y el puerto.", exc)
            return

        self._server = server
        transport.write_discovery(server.port, self._token)
        self._thread = _TransportThread(server)
        self._thread.start()
        logger.info("Puente MCP escuchando en %s:%s", transport.HOST, server.port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._thread.wait(int((transport.ACCEPT_POLL_SECONDS + transport.READ_TIMEOUT_SECONDS) * 1000))
            transport.remove_discovery(self._token)
        if self._log_handler is not None:
            logger.removeHandler(self._log_handler)
