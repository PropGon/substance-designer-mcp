"""Client for the plugin running inside Designer."""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any

from .config import designer_process_running, discovery_file

HOST = "127.0.0.1"
CONNECT_TIMEOUT_SECONDS = 3.0
RESPONSE_TIMEOUT_SECONDS = 130.0
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

DESIGNER_CLOSED = (
    "Substance 3D Designer no esta abierto. Abrelo y vuelve a intentarlo; "
    "el plugin sd_mcp_bridge se carga al iniciar. "
    "Las herramientas cook_sbs, render_outputs y batch_render funcionan sin Designer."
)
PLUGIN_NOT_LOADED = (
    "Designer esta abierto pero el plugin sd_mcp_bridge no responde. "
    "Revisa Tools > Plugin Manager para ver si aparece y esta activo. "
    "Si acabas de copiarlo, reinicia Designer. Si sigue igual, busca 'sd_mcp_bridge' en la "
    "consola de Designer: otro programa podria estar usando el puerto."
)


class BridgeUnavailable(RuntimeError):
    """The plugin cannot be reached; the message tells the user what to do."""


class BridgeCommandError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _unreachable_message() -> str:
    running = designer_process_running()
    if running is False:
        return DESIGNER_CLOSED
    if running is True:
        return PLUGIN_NOT_LOADED
    return f"No se pudo contactar con Designer. {DESIGNER_CLOSED} {PLUGIN_NOT_LOADED}"


def _read_discovery() -> dict:
    try:
        data = json.loads(discovery_file().read_text("utf-8"))
        return {"port": int(data["port"]), "token": str(data["token"])}
    except (OSError, ValueError, KeyError, TypeError):
        raise BridgeUnavailable(_unreachable_message()) from None


def call(command: str, params: dict | None = None, timeout: float = RESPONSE_TIMEOUT_SECONDS) -> Any:
    discovery = _read_discovery()
    request = {
        "id": uuid.uuid4().hex,
        "token": discovery["token"],
        "command": command,
        "params": params or {},
    }
    try:
        conn = socket.create_connection((HOST, discovery["port"]), timeout=CONNECT_TIMEOUT_SECONDS)
    except OSError:
        raise BridgeUnavailable(_unreachable_message()) from None

    with conn:
        conn.settimeout(timeout)
        try:
            conn.sendall(json.dumps(request).encode("utf-8") + b"\n")
            raw = _read_response(conn)
        except socket.timeout:
            raise BridgeUnavailable(
                "Designer no respondio a tiempo. Puede estar calculando o tener un dialogo abierto."
            ) from None
        except OSError as exc:
            raise BridgeUnavailable(f"Se perdio la conexion con Designer: {exc}") from None

    try:
        response = json.loads(raw)
    except ValueError:
        raise BridgeUnavailable("Designer cerro la conexion sin responder. Revisa si se ha cerrado.") from None

    if response.get("ok"):
        return response.get("result")
    error = response.get("error") or {}
    code = error.get("code", "unknown")
    if code == "unauthorized":
        raise BridgeUnavailable(
            "El token del puente no coincide: hay otro proceso en ese puerto o bridge.json esta obsoleto. "
            "Reinicia Designer."
        )
    raise BridgeCommandError(code, error.get("message", "Error desconocido en Designer."))


def _read_response(conn: socket.socket) -> bytes:
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = conn.recv(65536)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > MAX_RESPONSE_BYTES:
            raise OSError("La respuesta supera el limite permitido.")
    return bytes(buffer)
