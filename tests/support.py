import os
import subprocess

import pytest


def require(condition: bool, reason: str) -> None:
    """Skip locally, fail in CI when a required environment is missing."""
    if condition:
        return
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def cleanup_build(build_id: str | None, tag: str) -> None:
    """Best-effort removal of a build record and its image."""
    if build_id is not None:
        subprocess.run(
            ["docker", "buildx", "history", "rm", build_id],
            capture_output=True,
            text=True,
            check=False,
        )
    subprocess.run(
        ["docker", "image", "rm", "-f", tag],
        capture_output=True,
        text=True,
        check=False,
    )
