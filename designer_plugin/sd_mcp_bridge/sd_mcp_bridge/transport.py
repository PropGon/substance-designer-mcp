"""TCP transport for the bridge: newline-delimited JSON, one request per connection.

Standard library only, and never touches the ``sd`` module.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
from pathlib import Path
from typing import Any, Callable

HOST = "127.0.0.1"
DEFAULT_PORT = 9817
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
READ_TIMEOUT_SECONDS = 10.0
ACCEPT_POLL_SECONDS = 0.5

Dispatch = Callable[[str, dict], Any]


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def bridge_home() -> Path:
    override = os.environ.get("SD_MCP_HOME")
    return Path(override) if override else Path.home() / ".substance-designer-mcp"


def discovery_path() -> Path:
    return bridge_home() / "bridge.json"


def configured_port() -> int:
    env_port = os.environ.get("SD_MCP_PORT")
    if env_port:
        return int(env_port)
    config_file = bridge_home() / "config.json"
    if config_file.is_file():
        return int(json.loads(config_file.read_text("utf-8")).get("bridge_port", DEFAULT_PORT))
    return DEFAULT_PORT


def write_discovery(port: int, token: str) -> Path:
    path = discovery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"protocol": PROTOCOL_VERSION, "port": port, "token": token, "pid": os.getpid()}, handle)
    return path


def remove_discovery(token: str) -> None:
    # Only remove our own file: another Designer instance may have replaced it.
    path = discovery_path()
    try:
        if json.loads(path.read_text("utf-8")).get("token") == token:
            path.unlink()
    except (OSError, ValueError):
        pass


def new_token() -> str:
    return secrets.token_urlsafe(32)


def parse_request(raw: bytes, token: str) -> tuple[Any, str, dict]:
    try:
        message = json.loads(raw)
    except ValueError as exc:
        raise BridgeError("invalid_json", "El mensaje no es JSON valido.") from exc
    if not isinstance(message, dict):
        raise BridgeError("invalid_request", "El mensaje debe ser un objeto JSON.")
    if not hmac.compare_digest(str(message.get("token", "")).encode(), token.encode()):
        raise BridgeError("unauthorized", "Token invalido.")
    command = message.get("command")
    params = message.get("params", {})
    if not isinstance(command, str) or not command:
        raise BridgeError("invalid_request", "Falta 'command'.")
    if not isinstance(params, dict):
        raise BridgeError("invalid_request", "'params' debe ser un objeto.")
    return message.get("id"), command, params


def read_message(conn: socket.socket) -> bytes:
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = conn.recv(65536)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > MAX_MESSAGE_BYTES:
            raise BridgeError("too_large", "El mensaje supera el limite permitido.")
    return bytes(buffer.split(b"\n", 1)[0])


class BridgeTransport:
    """Loopback-only listener. The host is a constant on purpose: it is not configurable."""

    def __init__(self, token: str, dispatch: Dispatch, port: int = DEFAULT_PORT):
        self._token = token
        self._dispatch = dispatch
        self._requested_port = port
        self._listener: socket.socket | None = None
        self._stopping = False

    @property
    def port(self) -> int:
        return self._listener.getsockname()[1]

    def bind(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((HOST, self._requested_port))
            listener.listen(8)
        except OSError:
            listener.close()
            raise
        listener.settimeout(ACCEPT_POLL_SECONDS)
        self._listener = listener

    def serve_forever(self) -> None:
        while not self._stopping:
            try:
                conn, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                self._handle(conn)
        self._listener.close()

    def stop(self) -> None:
        self._stopping = True

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(READ_TIMEOUT_SECONDS)
        request_id = None
        try:
            raw = read_message(conn)
            if not raw:
                return
            request_id, command, params = parse_request(raw, self._token)
            response = {"id": request_id, "ok": True, "result": self._dispatch(command, params)}
        except BridgeError as exc:
            response = {"id": request_id, "ok": False, "error": {"code": exc.code, "message": exc.message}}
        except OSError:
            return
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}}
        try:
            conn.sendall(json.dumps(response, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
        except OSError:
            pass
