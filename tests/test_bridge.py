import json
import socket
import threading

import pytest

from sd_mcp_bridge import transport
from substance_designer_mcp import bridge_client


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def running_bridge(home):
    def dispatch(command, params):
        if command == "echo":
            return params
        if command == "boom":
            raise RuntimeError("fallo interno")
        raise transport.BridgeError("unknown_command", f"Comando desconocido: {command}")

    token = transport.new_token()
    server = transport.BridgeTransport(token, dispatch, port=0)
    server.bind()
    transport.write_discovery(server.port, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, token
    server.stop()
    thread.join(timeout=3)


def raw_exchange(port, payload: bytes) -> dict:
    with socket.create_connection((transport.HOST, port), timeout=3) as conn:
        conn.sendall(payload)
        return json.loads(conn.makefile().readline())


def test_round_trip_through_client(running_bridge):
    assert bridge_client.call("echo", {"a": 1, "texto": "ñ"}) == {"a": 1, "texto": "ñ"}


def test_unknown_command_is_rejected(running_bridge):
    with pytest.raises(bridge_client.BridgeCommandError) as error:
        bridge_client.call("rm_rf")
    assert error.value.code == "unknown_command"


def test_handler_exception_is_reported_not_fatal(running_bridge):
    with pytest.raises(bridge_client.BridgeCommandError, match="fallo interno"):
        bridge_client.call("boom")
    assert bridge_client.call("echo", {"sigue": True}) == {"sigue": True}


def test_wrong_token_never_reaches_dispatch(running_bridge):
    server, _ = running_bridge
    message = json.dumps({"id": 1, "token": "falso", "command": "echo"}).encode() + b"\n"
    response = raw_exchange(server.port, message)
    assert response["ok"] is False
    assert response["error"]["code"] == "unauthorized"


def test_http_request_is_rejected(running_bridge):
    server, _ = running_bridge
    response = raw_exchange(server.port, b"POST / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert response["error"]["code"] == "invalid_json"


@pytest.mark.parametrize(
    "fields, code",
    [({"params": {}}, "invalid_request"), ({"command": "echo", "params": []}, "invalid_request")],
)
def test_malformed_requests(running_bridge, fields, code):
    server, token = running_bridge
    message = json.dumps({"token": token, **fields}).encode() + b"\n"
    assert raw_exchange(server.port, message)["error"]["code"] == code


def test_oversized_message_is_rejected(running_bridge):
    server, _ = running_bridge
    with socket.create_connection((transport.HOST, server.port), timeout=5) as conn:
        try:
            conn.sendall(b"x" * (transport.MAX_MESSAGE_BYTES + 70000))
        except OSError:
            return
        assert json.loads(conn.makefile().readline())["error"]["code"] == "too_large"


def test_listens_only_on_loopback(running_bridge):
    server, _ = running_bridge
    assert server._listener.getsockname()[0] == "127.0.0.1"


def test_message_when_designer_closed(home, monkeypatch):
    monkeypatch.setattr(bridge_client, "designer_process_running", lambda: False)
    with pytest.raises(bridge_client.BridgeUnavailable, match="no esta abierto"):
        bridge_client.call("get_app_info")


def test_message_when_plugin_not_loaded(home, monkeypatch):
    monkeypatch.setattr(bridge_client, "designer_process_running", lambda: True)
    with pytest.raises(bridge_client.BridgeUnavailable, match="Plugin Manager"):
        bridge_client.call("get_app_info")


def test_stale_discovery_file_explains_what_to_do(home, monkeypatch):
    monkeypatch.setattr(bridge_client, "designer_process_running", lambda: False)
    with socket.socket() as probe:
        probe.bind((transport.HOST, 0))
        free_port = probe.getsockname()[1]
    transport.write_discovery(free_port, "viejo")
    with pytest.raises(bridge_client.BridgeUnavailable, match="no esta abierto"):
        bridge_client.call("get_app_info")


def test_remove_discovery_keeps_other_instance_file(home):
    transport.write_discovery(1234, "token-de-otra-instancia")
    transport.remove_discovery("mi-token")
    assert transport.discovery_path().exists()
    transport.remove_discovery("token-de-otra-instancia")
    assert not transport.discovery_path().exists()
