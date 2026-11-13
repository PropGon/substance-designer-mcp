"""Qt side of the bridge. Runs only inside Designer.

Follows Designer's documented threading pattern: the socket lives in a QThread and
hands each command to a QObject on the main thread through a queued signal, because
the ``sd`` API may only be called from the main application thread.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

from . import handlers, transport
from .qt_compat import QtCore

COMMAND_TIMEOUT_SECONDS = 120.0

logger = logging.getLogger("sd_mcp_bridge")


class _Call:
    def __init__(self, command: str, params: dict):
        self.command = command
        self.params = params
        self.future: Future = Future()


class MainThreadExecutor(QtCore.QObject):
    _requested = QtCore.Signal(object)

    def __init__(self, on_activity):
        super().__init__()
        self._on_activity = on_activity
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
        self._on_activity(call.command)
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
    """Can be started and stopped any number of times; each start uses a fresh token."""

    def __init__(self):
        self._executor = MainThreadExecutor(self._note_activity)
        self._server = None
        self._thread = None
        self._token = None
        self.port = None
        self.error = None
        self.last_command = None
        self.last_activity = 0.0

    @property
    def running(self) -> bool:
        return self._server is not None

    def _note_activity(self, command: str) -> None:
        self.last_command = command
        self.last_activity = time.monotonic()

    def start(self) -> bool:
        if self.running:
            return True
        token = transport.new_token()
        try:
            server = transport.BridgeTransport(token, self._executor.call, transport.configured_port())
            server.bind()
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            logger.error("sd_mcp_bridge no pudo iniciar el puente: %s. Revisa config.json y el puerto.", exc)
            return False
        self._server, self._token, self.port, self.error = server, token, server.port, None
        transport.write_discovery(server.port, token)
        self._thread = _TransportThread(server)
        self._thread.start()
        logger.info("Puente MCP escuchando en %s:%s", transport.HOST, server.port)
        return True

    def stop(self) -> None:
        if not self.running:
            return
        self._server.stop()
        self._thread.wait(int((transport.ACCEPT_POLL_SECONDS + transport.READ_TIMEOUT_SECONDS) * 1000))
        transport.remove_discovery(self._token)
        self._server = self._thread = self._token = self.port = None
        logger.info("Puente MCP detenido.")
