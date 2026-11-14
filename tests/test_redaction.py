from mcp_server_docker.redaction import redact_env


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
