from mcp_server_docker.redaction import redact_env, redact_error


def test_redact_env_hides_values_without_mutating_input():
    attrs = {
        "Config": {"Env": ["SECRET=abc", "URL=http://x?token=1", "FLAG"]},
        "ContainerConfig": {"Env": ["TOKEN=a=b"]},
        "Other": {"Env": ["KEEP=1"]},
    }

    redacted = redact_env(attrs)

    assert redacted["Config"]["Env"] == [
        "SECRET=<redacted>",
        "URL=<redacted>",
        "<redacted>",
    ]
    assert redacted["ContainerConfig"]["Env"] == ["TOKEN=<redacted>"]
    assert redacted["Other"]["Env"] == ["KEEP=1"]
    assert attrs["Config"]["Env"][0] == "SECRET=abc"


def test_redact_error_hides_sockets_urls_paths_and_env_values(monkeypatch):
    monkeypatch.setenv("DOCKER_AUTH_TOKEN", "debugtokenvalue")
    message = (
        "connection to unix:///var/run/docker.sock failed "
        "for tcp://user:secret@10.0.0.5:2375 "
        "(cert /etc/docker/ca.pem, token debugtokenvalue)"
    )

    redacted = redact_error(message)

    assert "docker.sock" not in redacted
    assert "user:secret" not in redacted
    assert "debugtokenvalue" not in redacted
    assert "/etc/docker/ca.pem" not in redacted
    assert "unix://<redacted>" in redacted
    assert "tcp://<redacted>@10.0.0.5:2375" in redacted
    assert "cert <redacted-path>" in redacted
    assert "token <redacted>" in redacted


def test_redact_error_hides_windows_paths():
    assert redact_error(r"open C:\Users\me\.docker\config.json: denied") == (
        "open <redacted-path>: denied"
    )
