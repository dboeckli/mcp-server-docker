# Integrationstests & Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coverage-Reporting mit 90-%-Schwelle in CI und eine kleine, robuste Docker-/Buildx-Integrationssuite, die die reale CLI-Grenze testet.

**Architecture:** Unit-Tests bleiben hermetic und schnell; der `integration`-Marker wird per Default abgewählt. Ein eigener CI-Job führt die markierten Tests gegen den echten Docker-Daemon aus. Integrationstests erzeugen je Test einen `FROM scratch`-Build, lesen den Build-`ref` aus `buildx_history` und räumen best-effort auf.

**Tech Stack:** Python 3.12, uv, pytest, anyio, pytest-cov, Docker/Buildx, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-08-integration-tests-coverage-design.md`

## Global Constraints

- Python 3.12; `uv` für Lock/Sync/Run.
- `pytest-cov` nur in der Dev-Gruppe; Coverage-Schwelle 90 % ausschließlich in CI.
- Integrationstests tragen `@pytest.mark.integration`; Default-`addopts` wählt sie ab.
- Skip mit klarer Meldung, wenn `docker` fehlt, der Daemon nicht erreichbar ist oder `buildx history` nicht funktioniert.
- Nur `FROM scratch`-Builds; keine Registry-Pulls, keine Netzabhängigkeit.
- Eindeutige Testnamen; Cleanup best-effort, Cleanup-Fehler lassen Tests nicht scheitern.
- Keine destruktiven Operationen an bestehenden Images/Containern.
- Commits nur nach expliziter Freigabe durch den Menschen.

## Review Focus

- Langer `ref` aus `buildx_history` (`<builder>/<node>/<id>`) → nicht-leere Logs.
- Nackte Build-ID → nicht-leere Logs.
- Logs ausschließlich auf stderr → gemergte, nicht-leere Ausgabe.
- Unbekannter `ref` → klarer `RuntimeError` mit „no record found“.
- Fehlende Docker-CLI → klarer `RuntimeError` (bestehender Unit-Test bleibt grün).

---

### Task 1: Coverage, pytest-Konfiguration und CI-Unit-Job

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md` (Development-Abschnitt)

**Interfaces:**
- Produces: Dev-Dependency `pytest-cov`; pytest-Marker `integration`; Default-`addopts = "-m 'not integration'"`; CI-Test-Job mit Coverage-Schwelle 90 %.

- [ ] **Step 1: Dev-Dependency und pytest-Konfiguration ergänzen**

In `pyproject.toml` in `[dependency-groups].dev` nach `"pytest>=8.3",` einfügen:

```toml
    "pytest-cov>=6",
```

Am Dateiende ergänzen:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not integration'"
markers = [
    "integration: requires a running Docker daemon and Buildx",
]
```

- [ ] **Step 2: Lockfile aktualisieren**

Run: `uv lock`  
Expected: `uv.lock` wird aktualisiert und enthält `pytest-cov`.

- [ ] **Step 3: Coverage-Artefakte ignorieren**

In `.gitignore` anhängen:

```gitignore
# Test / coverage artifacts
.coverage
htmlcov/
```

- [ ] **Step 4: CI-Unit-Job auf Coverage umstellen**

In `.github/workflows/ci.yml` im Job `test` den Schritt ersetzen:

```yaml
      - name: Test
        run: uv run pytest --cov=mcp_server_docker --cov-report=term-missing --cov-fail-under=90
```

- [ ] **Step 5: README-Testkommandos aktualisieren**

Im Development-Abschnitt den bestehenden Test-Block ersetzen durch:

```bash
uv run pytest
uv run pytest --cov=mcp_server_docker --cov-report=term-missing
uv run ruff format --check src tests
uv run ruff check src tests
```

- [ ] **Step 6: Unit-Suite und Coverage verifizieren**

Run: `uv run pytest`  
Expected: 13 passed, keine Integrationstests gesammelt.

Run: `uv run pytest --cov=mcp_server_docker --cov-report=term-missing --cov-fail-under=90`  
Expected: 13 passed, Coverage ≥ 90 %, Exit-Code 0.

- [ ] **Step 7: Commit (nur nach Freigabe)**

```bash
git add pyproject.toml uv.lock .gitignore .github/workflows/ci.yml README.md
git commit -m "Add coverage reporting and pytest integration marker"
```

---

### Task 2: Integrations-Fixtures

**Files:**
- Create: `tests/integration/conftest.py`
- Test: `tests/integration/test_build_record.py`

**Interfaces:**
- Consumes: `mcp_server_docker.server.buildx_history() -> list[dict[str, Any]]`
- Produces:
  - `docker_daemon` (Session-Fixture): skippt, wenn Docker-CLI oder Daemon fehlt.
  - `buildx_history_ready` (Session-Fixture): skippt, wenn `docker buildx history ls` fehlschlägt.
  - `build_record` (Function-Fixture) → `dict[str, str]` mit `ref`, `build_id`, `tag`, `name`.

- [ ] **Step 1: Failing Test für die Fixture schreiben**

Create `tests/integration/test_build_record.py`:

```python
import pytest


@pytest.mark.integration
def test_build_record_exposes_its_own_ref(build_record):
    assert build_record["build_id"]
    assert build_record["ref"].endswith(build_record["build_id"])
    assert build_record["tag"].startswith("mcp-server-docker-it:")
    assert build_record["name"].startswith("ctx-")
```

- [ ] **Step 2: Test rot laufen lassen**

Run: `uv run pytest -o addopts= -m integration tests/integration/test_build_record.py -v`  
Expected: FAIL mit „fixture 'build_record' not found“.

- [ ] **Step 3: Fixtures implementieren**

Create `tests/integration/conftest.py`:

```python
import shutil
import subprocess
import uuid

import pytest

import mcp_server_docker.server as server_module


@pytest.fixture(scope="session")
def docker_daemon():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not found")
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"docker daemon not reachable: {result.stderr.strip()}")
    return True


@pytest.fixture(scope="session")
def buildx_history_ready(docker_daemon):
    result = subprocess.run(
        ["docker", "buildx", "history", "ls"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"buildx history not available: {result.stderr.strip() or result.stdout.strip()}"
        )
    return True


@pytest.fixture
def build_record(buildx_history_ready, tmp_path):
    unique = uuid.uuid4().hex[:12]
    context = tmp_path / f"ctx-{unique}"
    context.mkdir()
    (context / "Dockerfile").write_text(
        "FROM scratch\nCOPY hello.txt /hello.txt\n", encoding="utf-8"
    )
    (context / "hello.txt").write_text("hello\n", encoding="utf-8")
    tag = f"mcp-server-docker-it:{unique}"

    before = {record["ref"] for record in server_module.buildx_history()}
    build = subprocess.run(
        ["docker", "buildx", "build", "-t", tag, "--progress", "plain", str(context)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr

    new_records = [
        record
        for record in server_module.buildx_history()
        if record["ref"] not in before
    ]
    record = next((r for r in new_records if r.get("name") == context.name), None)
    if record is None:
        pytest.skip("buildx did not record build history for the test build")

    ref = record["ref"]
    build_id = ref.rsplit("/", 1)[-1]
    yield {"ref": ref, "build_id": build_id, "tag": tag, "name": context.name}

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
```

- [ ] **Step 4: Test grün laufen lassen**

Run: `uv run pytest -o addopts= -m integration tests/integration/test_build_record.py -v`  
Expected: PASS (oder SKIP mit klarer Begründung, wenn Docker/Buildx fehlt).

- [ ] **Step 5: Commit (nur nach Freigabe)**

```bash
git add tests/integration/conftest.py tests/integration/test_build_record.py
git commit -m "Add Docker integration test fixtures"
```

---

### Task 3: Integrationstests für die CLI-Grenze

**Files:**
- Create: `tests/integration/test_docker_cli.py`

**Interfaces:**
- Consumes: Fixture `build_record` aus Task 2.
- Consumes: `server_module.buildx_logs(ref: str, builder: str | None = None, progress: Literal["plain", "rawjson", "tty"] = "plain") -> str`
- Consumes: `server_module._run_docker(*args: str, combine_stderr: bool = False) -> str`

- [ ] **Step 1: Test für langen `ref` schreiben**

Create `tests/integration/test_docker_cli.py` mit:

```python
import pytest

import mcp_server_docker.server as server_module


@pytest.mark.integration
def test_buildx_logs_returns_logs_for_full_ref(build_record):
    logs = server_module.buildx_logs(build_record["ref"])
    assert logs.strip()
    assert "hello.txt" in logs
```

- [ ] **Step 2: Test laufen lassen**

Run: `uv run pytest -o addopts= -m integration tests/integration/test_docker_cli.py::test_buildx_logs_returns_logs_for_full_ref -v`  
Expected: PASS gegen den aktuellen Fix; FAIL bedeutet Regression, dann stoppen und untersuchen.

- [ ] **Step 3: Restliche Tests ergänzen**

In derselben Datei anhängen:

```python
@pytest.mark.integration
def test_buildx_logs_returns_logs_for_bare_id(build_record):
    logs = server_module.buildx_logs(build_record["build_id"])
    assert logs.strip()
    assert "hello.txt" in logs


@pytest.mark.integration
def test_buildx_logs_unknown_ref_raises(build_record):
    with pytest.raises(RuntimeError, match="no record found"):
        server_module.buildx_logs("mcp-server-docker-does-not-exist")


@pytest.mark.integration
def test_run_docker_merges_stderr_for_buildx_logs(build_record):
    output = server_module._run_docker(
        "buildx", "history", "logs", build_record["build_id"], combine_stderr=True
    )
    assert output.strip()
    assert "hello.txt" in output
```

- [ ] **Step 4: Alle Integrationstests laufen lassen**

Run: `uv run pytest -o addopts= -m integration -v`  
Expected: 5 passed (oder SKIPs mit klarer Begründung, wenn Docker/Buildx fehlt).

- [ ] **Step 5: Unit-Test für fehlende CLI gegenprüfen**

Run: `uv run pytest tests/test_server.py::test_buildx_reports_missing_docker_cli -v`  
Expected: PASS.

- [ ] **Step 6: Commit (nur nach Freigabe)**

```bash
git add tests/integration/test_docker_cli.py
git commit -m "Add Docker CLI integration tests"
```

---

### Task 4: CI-Integrationsjob und README

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md` (Development-Abschnitt)

**Interfaces:**
- Produces: CI-Job `integration`, der nach `test` läuft und `uv run pytest -o addopts= -m integration` ausführt.

- [ ] **Step 1: Integrationsjob ergänzen**

In `.github/workflows/ci.yml` nach dem Job `test` und vor `docker` einfügen:

```yaml
  integration:
    name: Integration tests
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
          enable-cache: true
      - name: Install dependencies
        run: uv sync --all-groups --frozen
      - name: Run integration tests
        run: uv run pytest -o addopts= -m integration
```

- [ ] **Step 2: Workflow validieren**

Run: `go run github.com/rhysd/actionlint/cmd/actionlint@latest .github/workflows/ci.yml`  
Expected: keine Ausgabe, Exit-Code 0.

- [ ] **Step 3: README um Integrationskommandos ergänzen**

Im Development-Abschnitt nach dem Unit-/Coverage-Block einfügen:

````markdown
Run the Docker integration tests (requires Docker and Buildx):

```bash
uv run pytest -o addopts= -m integration
```
````

- [ ] **Step 4: Gesamte Suite verifizieren**

Run: `uv run pytest`  
Expected: 13 passed, Integrationstests abgewählt.

Run: `uv run pytest -o addopts= -m integration -v`  
Expected: 5 passed (oder SKIPs mit klarer Begründung).

- [ ] **Step 5: Commit (nur nach Freigabe)**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "Run integration tests in CI"
```
