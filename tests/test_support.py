import subprocess

import pytest

from tests.support import cleanup_build, require


def test_require_skips_outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception):
        require(False, "missing dependency")


def test_require_fails_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception):
        require(False, "missing dependency")


def test_require_returns_when_condition_is_true():
    require(True, "unused")


def test_cleanup_build_removes_history_and_image(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("tests.support.subprocess.run", fake_run)
    cleanup_build("abc", "image:tag")
    assert calls == [
        ["docker", "buildx", "history", "rm", "abc"],
        ["docker", "image", "rm", "-f", "image:tag"],
    ]


def test_cleanup_build_without_build_id_only_removes_image(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("tests.support.subprocess.run", fake_run)
    cleanup_build(None, "image:tag")
    assert calls == [["docker", "image", "rm", "-f", "image:tag"]]
