"""Guards release metadata: name and version come from a single source."""

from importlib.metadata import version

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
