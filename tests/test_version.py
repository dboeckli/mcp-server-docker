"""Guards release metadata: name and version come from a single source."""

import json
from importlib.metadata import version
from pathlib import Path

from mcp_server_docker._version import __version__

DISTRIBUTION = "mcp-server-docker-dboeckli"


def test_installed_metadata_matches_version_module():
    """The built metadata must not drift from the version module."""
    assert version(DISTRIBUTION) == __version__


def test_version_is_a_plain_release_number():
    """A git tag ``vX.Y.Z`` must map onto the version string unchanged."""
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_registry_metadata_matches_version():
    """server.json must track the version module and the release name."""
    path = Path(__file__).resolve().parents[1] / "server.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["name"] == "io.github.dboeckli/mcp-server-docker"
    assert data["version"] == __version__
    assert 1 <= len(data["description"]) <= 100

    pypi = [p for p in data["packages"] if p["registryType"] == "pypi"]
    oci = [p for p in data["packages"] if p["registryType"] == "oci"]
    assert [p["version"] for p in pypi] == [__version__]
    assert [p["identifier"].rsplit(":", 1)[1] for p in oci] == [__version__]
