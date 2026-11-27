from types import SimpleNamespace

import pytest

from mcp_server_docker import server as server_module

MAX_LOG_BYTES = 20 * 1024


def _fake_client(raw: bytes, calls: list[dict]):
    class FakeContainer:
        def logs(self, **kwargs):
            calls.append(kwargs)
            return raw

    return SimpleNamespace(
        containers=SimpleNamespace(get=lambda _container_id: FakeContainer())
    )


@pytest.mark.parametrize("tail", [100, "all"])
def test_fetch_logs_bounds_large_invalid_utf8_and_retains_metadata(monkeypatch, tail):
    raw = b"HEAD\n" + b"x" * (MAX_LOG_BYTES + 7) + b"\xffTAIL"
    calls: list[dict] = []
    monkeypatch.setattr(server_module, "_client", lambda _ctx: _fake_client(raw, calls))

    result = server_module.docker_fetch_container_logs(None, "container", tail=tail)

    assert calls == [{"tail": tail}]
    assert result["truncated"] is True
    assert result["bytes"] == len(raw)
    text = "\n".join(result["logs"])
    assert "HEAD" not in text
    assert "\ufffdTAIL" in text
    assert len(text.encode("utf-8")) <= MAX_LOG_BYTES + 3


@pytest.mark.parametrize(
    ("size", "truncated"),
    [(0, False), (MAX_LOG_BYTES, False), (MAX_LOG_BYTES + 1, True)],
)
def test_fetch_logs_truncation_flag_at_the_boundary(monkeypatch, size, truncated):
    raw = b"y" * size
    monkeypatch.setattr(server_module, "_client", lambda _ctx: _fake_client(raw, []))

    result = server_module.docker_fetch_container_logs(None, "container")

    assert result["truncated"] is truncated
    assert result["bytes"] == size
    assert "".join(result["logs"]).count("y") == min(size, MAX_LOG_BYTES)
