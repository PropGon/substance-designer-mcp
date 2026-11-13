"""MCP menu and status indicator inside Designer.

The menu uses Designer's official UI manager. The status bar indicator goes through Qt
directly, so it is optional: if a future Designer moves the status bar, the menu keeps
working and its title still shows the state.
"""

from __future__ import annotations

import logging
import time

import sd

from . import transport
from .qt_compat import QAction, QtCore, QtWidgets

MENU_ID = "sd_mcp_bridge_menu"
BUSY_SECONDS = 4.0

logger = logging.getLogger("sd_mcp_bridge")

STATES = {
    "off": ("#8E9297", "MCP ○", "Apagado: Claude no puede usar Designer."),
    "idle": ("#3FB950", "MCP ●", "Activo: esperando a Claude."),
    "busy": ("#00F2FF", "MCP ◉", "En uso"),
    "error": ("#F85149", "MCP ✕", "No se pudo activar"),
}


class BridgeUi(QtCore.QObject):
    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self._menu = None
        self._label = None
        self._status_bar = None
        self._ui_manager = sd.getContext().getSDApplication().getQtForPythonUIMgr()
        self._build_menu()
        self._build_status_label()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    # ------------------------------------------------------------------ building

    def _build_menu(self) -> None:
        if self._ui_manager is None or not hasattr(self._ui_manager, "newMenu"):
            logger.warning("Esta version de Designer no permite crear menus desde Python; el puente sigue funcionando.")
            return
        try:
            self._menu = self._ui_manager.newMenu("MCP", MENU_ID)
        except Exception as exc:
            logger.warning("No se pudo crear el menu MCP: %s", exc)
            return
        self._status_action = QAction("", self._menu)
        self._status_action.setEnabled(False)
        self._toggle_action = QAction("", self._menu)
        self._toggle_action.triggered.connect(self._toggle)
        self._autostart_action = QAction("Activar al abrir Designer", self._menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(self._autostart())
        self._autostart_action.toggled.connect(self._set_autostart)
        for action in (self._status_action, self._toggle_action):
            self._menu.addAction(action)
        self._menu.addSeparator()
        self._menu.addAction(self._autostart_action)

    def _build_status_label(self) -> None:
        try:
            window = self._ui_manager.getMainWindow() if self._ui_manager is not None else None
            status_bar = window.statusBar() if isinstance(window, QtWidgets.QMainWindow) else None
            if status_bar is None:
                return
            self._label = QtWidgets.QLabel()
            self._label.setTextFormat(QtCore.Qt.RichText)
            self._label.setContentsMargins(8, 0, 8, 0)
            status_bar.addPermanentWidget(self._label)
            self._status_bar = status_bar
        except Exception as exc:
            self._label = None
            logger.warning("No se pudo agregar el indicador a la barra de estado: %s", exc)

    # ------------------------------------------------------------------ state

    def _state(self) -> tuple[str, str]:
        bridge = self._bridge
        if bridge.error and not bridge.running:
            return "error", f"{STATES['error'][2]}: {bridge.error}"
        if not bridge.running:
            return "off", STATES["off"][2]
        if bridge.last_command and time.monotonic() - bridge.last_activity < BUSY_SECONDS:
            return "busy", f"En uso: {bridge.last_command}"
        detail = f"Activo en el puerto {bridge.port}"
        if bridge.last_command:
            detail += f" · ultima herramienta: {bridge.last_command}"
        return "idle", detail

    @QtCore.Slot()
    def refresh(self) -> None:
        state, detail = self._state()
        color, title, _ = STATES[state]
        if self._menu is not None:
            self._menu.setTitle(title)
            self._status_action.setText(detail)
            self._toggle_action.setText("Desactivar el puente" if self._bridge.running else "Activar el puente")
        if self._label is not None:
            self._label.setText(f'<span style="color:{color}">●</span> MCP')
            self._label.setToolTip(detail)

    def _toggle(self) -> None:
        if self._bridge.running:
            self._bridge.stop()
        else:
            self._bridge.start()
        self.refresh()

    @staticmethod
    def _autostart() -> bool:
        try:
            return transport.autostart_enabled()
        except (OSError, ValueError):
            return True

    def _set_autostart(self, enabled: bool) -> None:
        try:
            transport.write_config_value("autostart", bool(enabled))
        except (OSError, ValueError) as exc:
            logger.error("No se pudo guardar la preferencia: %s", exc)

    # ------------------------------------------------------------------ teardown

    def dispose(self) -> None:
        self._timer.stop()
        if self._label is not None and self._status_bar is not None:
            try:
                self._status_bar.removeWidget(self._label)
                self._label.deleteLater()
            except RuntimeError:
                pass
        if self._menu is not None and hasattr(self._ui_manager, "deleteMenu"):
            try:
                self._ui_manager.deleteMenu(MENU_ID)
            except Exception:
                pass
