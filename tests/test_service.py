"""The local service (POST /v1/memory), the client that starts it, and the MCP server."""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cogito_mem import ApiError, Client, Memory
from cogito_mem.mcp_server import INSTRUCTIONS, PROTOCOL_VERSIONS, McpServer
from cogito_mem.server import MemoryServer

SRC = str(Path(__file__).resolve().parents[1] / "src")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    mem = Memory(tmp_path / "home", embedder="hash")
    srv = MemoryServer(mem, port=0)
    thread = threading.Thread(target=srv.serve, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    mem.close()


def post(srv, body, path="/v1/memory", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    conn.request("POST", path, body=data, headers=headers or {"Content-Type": "application/json"})
    resp = conn.getresponse()
    out = resp.status, json.loads(resp.read())
    conn.close()
    return out


def test_http_append_and_query(server):
    status, resp = post(server, {"op": "append", "items": [{"author": "user", "text": "The mascot is a squirrel."}]})
    assert status == 200 and resp["items"][0]["status"] == "added"
    status, resp = post(server, {"op": "query", "text": "mascot"})
    assert status == 200 and resp["items"][0]["text"] == "The mascot is a squirrel."
    assert set(resp) == {"items", "as_of", "tokens", "took_ms"}


def test_http_errors_use_aip_codes(server):
    assert post(server, {"op": "query", "text": "x", "top_k": 500}) == (
        400,
        {"error": {"code": "invalid_argument", "message": "top_k must be between 1 and 100, got 500"}},
    )
    status, body = post(server, b"{not json")
    assert status == 400 and body["error"]["code"] == "invalid_argument"
    status, body = post(server, {"op": "query", "text": "x"}, path="/v2/other")
    assert status == 404 and body["error"]["code"] == "not_found"
    status, body = post(
        server, {"op": "append", "items": [{"author": "a", "text": "x", "retracts": ["0192f3a1-7c2e-7d10-9b1a-5e2f0c8a4d31"]}]}
    )
    assert status == 404 and body["error"]["code"] == "not_found"


def test_http_refuses_browser_style_requests(server):
    # a cross-site form or fetch without JSON content type cannot write
    status, body = post(server, {"op": "append", "items": [{"author": "a", "text": "x"}]}, headers={"Content-Type": "text/plain"})
    assert status == 400 and "Content-Type" in body["error"]["message"]
    # DNS rebinding: a foreign Host header is refused
    status, body = post(
        server, {"op": "query", "text": "x"}, headers={"Content-Type": "application/json", "Host": "evil.example:7327"}
    )
    assert status == 403 and body["error"]["code"] == "permission_denied"


def test_http_status_and_run_file(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", "/v1/status")
    info = json.loads(conn.getresponse().read())
    assert info["status"] == "ok" and info["pid"] == os.getpid()
    run_file = server.memory.root / "run" / "server.json"
    assert json.loads(run_file.read_text())["url"] == server.url


def test_client_talks_to_a_running_server(server, tmp_path):
    client = Client(url=server.url, root=tmp_path / "client")  # its own folder holds the name it sends
    client.append([{"author": "user", "text": "client test note"}])
    assert client.query("client test")["items"][0]["text"] == "client test note"
    with pytest.raises(ApiError) as err:
        client.query("x", top_k=0)
    assert err.value.code == "invalid_argument"


def test_client_without_autostart_reports_unavailable(tmp_path):
    client = Client(url=f"http://127.0.0.1:{free_port()}", root=tmp_path)
    with pytest.raises(ApiError) as err:
        client.query("x")
    assert err.value.code == "unavailable"
    assert client.status() is None


@pytest.mark.slow
def test_client_starts_the_service_on_demand_and_stops_it(tmp_path, monkeypatch):
    port = free_port()
    monkeypatch.setenv("COGITO_MEM_PORT", str(port))
    monkeypatch.setenv("PYTHONPATH", SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    root = tmp_path / "home"
    client = Client(root=root, serve_args=["--embedder", "hash", "--idle-timeout", "120"])
    try:
        resp = client.append([{"author": "user", "text": "autostarted"}])
        assert resp["items"][0]["status"] == "added"
        assert client.url == f"http://127.0.0.1:{port}"
        info = client.status()
        assert info["root"] == str(root) and info["pid"] != os.getpid()
        # a second client finds the same service through the run file
        assert Client(root=root).query("autostarted")["items"][0]["text"] == "autostarted"
    finally:
        assert client.stop_server()
    assert client.status() is None
    assert not (root / "run" / "server.json").exists()


@pytest.mark.slow
def test_service_stops_when_idle(tmp_path):
    port = free_port()
    env = dict(os.environ, PYTHONPATH=SRC)
    log = tmp_path / "serve.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "cogito_mem", "--root", str(tmp_path / "h"), "serve", "--embedder", "hash",
             "--port", str(port), "--idle-timeout", "0.5"],
            env=env, stdout=out, stderr=subprocess.STDOUT,
        )  # fmt: skip
        try:
            assert proc.wait(timeout=20) == 0
        except subprocess.TimeoutExpired:
            if hasattr(signal, "SIGUSR1"):
                proc.send_signal(signal.SIGUSR1)  # dump every thread's stack into the log
                time.sleep(1)
            proc.kill()
            pytest.fail("serve did not stop when idle:\n" + log.read_text())


# --------------------------------------------------------------------------- MCP


def rpc(server: McpServer, method: str, params: dict | None = None, id_: int | None = 1) -> dict | None:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if id_ is not None:
        msg["id"] = id_
    return server.dispatch(msg)


def test_mcp_initialize_and_tools(mem):
    srv = McpServer(mem.handle)
    init = rpc(srv, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "claude-code", "version": "2.1"}})["result"]  # fmt: skip
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "cogito-mem"
    assert init["instructions"] == INSTRUCTIONS
    assert "memory_query" in INSTRUCTIONS and "memory_append" in INSTRUCTIONS
    assert rpc(srv, "notifications/initialized", id_=None) is None
    unknown = rpc(srv, "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert unknown["protocolVersion"] == PROTOCOL_VERSIONS[0]
    tools = {t["name"]: t for t in rpc(srv, "tools/list")["result"]["tools"]}
    assert set(tools) == {"memory_append", "memory_query"}
    assert set(tools["memory_append"]["inputSchema"]["properties"]) == {"text", "title"}
    assert set(tools["memory_query"]["inputSchema"]["properties"]) == {"text", "valid_after", "valid_before", "max_tokens"}
    assert "a week ago" in tools["memory_query"]["description"]
    assert rpc(srv, "ping")["result"] == {}
    assert rpc(srv, "no/such")["error"]["code"] == -32601


def test_mcp_tool_calls_fill_in_server_side_keys(mem):
    srv = McpServer(mem.handle, thread_id="session-42")
    rpc(srv, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-code"}})
    res = rpc(srv, "tools/call", {"name": "memory_append", "arguments": {"text": "Decision: ship v0 on Friday.", "title": "release"}})["result"]
    assert res["isError"] is False
    appended = json.loads(res["content"][0]["text"])
    assert appended == res["structuredContent"] and appended["items"][0]["status"] == "added"
    res = rpc(srv, "tools/call", {"name": "memory_query", "arguments": {"text": "ship v0", "max_tokens": 50}})["result"]
    resp = json.loads(res["content"][0]["text"])
    assert set(resp) == {"items", "as_of", "tokens", "took_ms"}  # exactly the §3.2 response
    item = resp["items"][0]
    assert item["author"] == "claude-code" and item["thread_id"] == "session-42"
    assert item["source"]["title"] == "release"


def test_mcp_tool_errors_are_results_not_crashes(mem):
    srv = McpServer(mem.handle)
    res = rpc(srv, "tools/call", {"name": "memory_query", "arguments": {"text": "x", "valid_after": "last week"}})["result"]
    assert res["isError"] is True and json.loads(res["content"][0]["text"])["error"]["code"] == "invalid_argument"
    res = rpc(srv, "tools/call", {"name": "memory_query", "arguments": {"text": "x", "colour": "red"}})["result"]
    assert res["isError"] is True
    assert rpc(srv, "tools/call", {"name": "memory_delete", "arguments": {}})["error"]["code"] == -32602


def test_mcp_stdio_process(tmp_path):
    env = dict(os.environ, PYTHONPATH=SRC)
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "codex-mcp-client", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_append", "arguments": {"text": "stdio works"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_query", "arguments": {"text": "stdio"}}},
    ]  # fmt: skip
    stdin = "\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"
    out = subprocess.run(
        [sys.executable, "-m", "cogito_mem", "--root", str(tmp_path / "h"), "mcp", "--in-process", "--embedder", "hash"],
        input=stdin.encode(), capture_output=True, env=env, timeout=60,
    )  # fmt: skip
    lines = [json.loads(line) for line in out.stdout.decode().splitlines()]
    assert [m.get("id") for m in lines] == [1, 2, 3, None]
    assert lines[0]["result"]["protocolVersion"] == "2025-03-26"
    found = json.loads(lines[2]["result"]["content"][0]["text"])["items"][0]
    assert found["text"] == "stdio works" and found["author"] == "codex-mcp-client"
    assert lines[3]["error"]["code"] == -32700


def test_mcp_with_the_official_python_sdk_client(tmp_path):
    mcp = pytest.importorskip("mcp")
    import anyio
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cogito_mem", "--root", str(tmp_path / "h"), "mcp", "--in-process", "--embedder", "hash"],
        env={**os.environ, "PYTHONPATH": SRC},
    )

    def attr(obj, *names):  # the SDK renamed fields to snake_case in 2.x
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        raise AttributeError(names[0])

    async def run():
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                init = await session.initialize()
                assert attr(init, "server_info", "serverInfo").name == "cogito-mem"
                tools = await session.list_tools()
                assert sorted(t.name for t in tools.tools) == ["memory_append", "memory_query"]
                res = await session.call_tool("memory_append", {"text": "The SDK client saved this idea."})
                assert not attr(res, "is_error", "isError")
                res = await session.call_tool("memory_query", {"text": "SDK idea", "max_tokens": 100})
                assert not attr(res, "is_error", "isError")
                payload = json.loads(res.content[0].text)
                assert payload["items"][0]["text"] == "The SDK client saved this idea."
                assert attr(res, "structured_content", "structuredContent") == payload

    anyio.run(run)


# --------------------------------------------------------------------------- MCP over HTTP


def mcp_post(srv, body, session=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        h["Mcp-Session-Id"] = session
    h.update(headers or {})
    conn.request("POST", "/mcp", body=json.dumps(body), headers=h)
    resp = conn.getresponse()
    raw = resp.read()
    out = resp.status, (json.loads(raw) if raw else None), resp.getheader("Mcp-Session-Id")
    conn.close()
    return out


def test_mcp_over_http(server):
    status, init, session = mcp_post(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude-code", "version": "2"}}})  # fmt: skip
    assert status == 200 and session and init["result"]["serverInfo"]["name"] == "cogito-mem"
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    assert status == 202 and body is None
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "memory_append", "arguments": {"text": "Saved over HTTP MCP."}}}, session)  # fmt: skip
    assert status == 200 and body["result"]["isError"] is False
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "memory_query", "arguments": {"text": "HTTP MCP"}}}, session)  # fmt: skip
    item = body["result"]["structuredContent"]["items"][0]
    assert item["text"] == "Saved over HTTP MCP." and item["author"] == "claude-code" and item["thread_id"] == "default"
    # an unknown session must initialize again; a browser origin is refused
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, "nope")
    assert status == 404
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, session,
                               {"Origin": "https://evil.example"})  # fmt: skip
    assert status == 403
    status, body, _ = mcp_post(server, {"jsonrpc": "2.0", "id": 6, "method": "tools/list"}, session,
                               {"Origin": "http://localhost:3000"})  # fmt: skip
    assert status == 200 and len(body["result"]["tools"]) == 2
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", "/mcp")
    assert conn.getresponse().status == 405


def test_mcp_over_http_with_the_official_sdk(server):
    mcp = pytest.importorskip("mcp")
    streamable = pytest.importorskip("mcp.client.streamable_http")
    client_factory = getattr(streamable, "streamable_http_client", None) or getattr(streamable, "streamablehttp_client")
    import anyio

    async def run():
        async with client_factory(server.url + "/mcp?namespace=sdk") as streams:
            read, write = streams[0], streams[1]
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert sorted(t.name for t in tools.tools) == ["memory_append", "memory_query"]
                await session.call_tool("memory_append", {"text": "The SDK reached the memory over HTTP."})
                res = await session.call_tool("memory_query", {"text": "SDK over HTTP"})
                payload = json.loads(res.content[0].text)
                assert payload["items"][0]["text"] == "The SDK reached the memory over HTTP."

    anyio.run(run)
    # the namespace from the URL was used
    assert server.memory.namespace("sdk").stats()["messages"] == 1


def test_allowed_hosts_can_be_extended(tmp_path, monkeypatch):
    monkeypatch.setenv("COGITO_MEM_ALLOWED_HOSTS", "cogito-mem, host.docker.internal")
    mem = Memory(None, embedder=None)
    srv = MemoryServer(mem, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _ = post(srv, {"op": "query", "text": "x"}, headers={"Content-Type": "application/json", "Host": "cogito-mem:7327"})
        assert status == 200
        status, _ = post(srv, {"op": "query", "text": "x"}, headers={"Content-Type": "application/json", "Host": "other:7327"})
        assert status == 403
    finally:
        srv.shutdown()
        mem.close()
