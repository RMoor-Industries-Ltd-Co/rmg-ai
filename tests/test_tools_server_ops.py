"""tools_server_ops.py's one safety-critical property: the tailnet proxy is scoped to exactly
this client's own requests.post call, never a container-wide HTTP_PROXY/HTTPS_PROXY env var
that would silently route every other tool's traffic (Anthropic, Gmail, Drive, ClickUp, ...)
through the tailscale-serverops sidecar too."""

import pytest

from allen import tools_server_ops
from allen.config import settings


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "piaar_serverops_endpoint", "http://piaar-preview.example:8793/mcp")
    monkeypatch.setattr(settings, "piaar_key_serverops_allen", "a-test-key-thats-long-enough")


def _fake_response(json_body):
    class _Resp:
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

        def json(self):
            return json_body

    return _Resp()


def test_call_passes_no_proxy_when_unset(configured, monkeypatch):
    monkeypatch.setattr(settings, "piaar_serverops_proxy", "")
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _fake_response({"result": {"content": [{"type": "text", "text": "ok"}]}})

    monkeypatch.setattr(tools_server_ops.requests, "post", fake_post)
    tools_server_ops._call("server_ops_whoami", {})
    assert captured["proxies"] is None


def test_call_scopes_proxy_to_this_request_only(configured, monkeypatch):
    monkeypatch.setattr(settings, "piaar_serverops_proxy", "http://tailscale-serverops:1055")
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _fake_response({"result": {"content": [{"type": "text", "text": "ok"}]}})

    monkeypatch.setattr(tools_server_ops.requests, "post", fake_post)
    tools_server_ops._call("server_ops_whoami", {})
    assert captured["proxies"] == {
        "http": "http://tailscale-serverops:1055",
        "https": "http://tailscale-serverops:1055",
    }


def test_handle_defaults_server_id_to_piaar_preview(configured, monkeypatch):
    monkeypatch.setattr(settings, "piaar_serverops_proxy", "")
    seen_args = {}

    def fake_call(tool_name, arguments):
        seen_args.update(arguments)
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}

    monkeypatch.setattr(tools_server_ops, "_call", fake_call)
    tools_server_ops.handle("server_status", {})
    assert seen_args["serverId"] == tools_server_ops.DEFAULT_SERVER_ID


def test_handle_reports_not_connected_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "piaar_serverops_endpoint", "")
    monkeypatch.setattr(settings, "piaar_key_serverops_allen", "")
    assert tools_server_ops.handle("server_status", {}) == "server-ops isn't connected yet."
