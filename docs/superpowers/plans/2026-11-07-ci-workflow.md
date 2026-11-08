# CI Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Actions CI, die bei Push/PR Lint und Tests ausführt, das Docker-Image baut und bei `v*`-Tags nach GHCR pusht.

**Architecture:** Ein Workflow mit zwei Jobs. `test` läuft mit `uv` (Python 3.12) und `ruff`/`pytest`; `docker` hängt per `needs` davon ab, baut mit Buildx und pusht nur bei Tags. Ein GHCR-Login passiert ebenfalls nur bei Tags.

**Tech Stack:** GitHub Actions, `astral-sh/setup-uv`, `ruff`, `pytest`, `docker/build-push-action`, GHCR.

**Spec:** Im Chat freigegebenes Kurz-Design vom 2026-11-07 (dieser Plan setzt es um).

## Global Constraints

- Python-Version: nur `3.12`.
- GHCR-Push ausschließlich bei Tags `v*`; Pull Requests und `main` bauen nur.
- Kein PyPI-Publish, kein `edge`-Tag, keine Multi-Arch-Matrix.
- Keine Commits ohne explizite Anweisung.

## Review Focus

- **Tag-Erkennung:** `github.ref` ist bei Tags `refs/tags/vX.Y.Z`; Login, Push und `latest` müssen genau dann aktiv sein, sonst schlägt der Push fehl oder unterbleibt.
- **Fork-PRs:** `GITHUB_TOKEN` hat dort keine `packages: write`-Rechte; der Push muss durch die Tag-Bedingung sicher übersprungen werden.
- **Lokaler Subprozess-Test:** `test_production_stdio_command_lists_tools` startet `uv run mcp-server-docker`; im CI muss `uv` auf dem `PATH` liegen und die Umgebung synchronisiert sein.
- **Leere Image-Tags bei PRs:** `metadata-action` liefert ohne Tag keine Semver-Tags; der Build darf trotzdem nicht fehlschlagen.
- **YAML-/Action-Semantik:** Ein Tippfehler in `on`, `permissions` oder `with` fällt in pytest nicht auf; deshalb `actionlint`.

---

### Task 1: CI-Workflow anlegen und lokal verifizieren

**Files:**
- Create: `.github/workflows/ci.yml`
- Verify: `docs/superpowers/plans/2026-11-07-ci-workflow.md`

**Interfaces:**
- Consumes: nichts.
- Produces: Workflow `CI` mit Jobs `test` und `docker`; Image `ghcr.io/<owner>/<repo>` mit Tags `X.Y.Z`, `X.Y`, `latest` bei `v*`.

- [ ] **Step 1: Workflow-Datei anlegen**

```yaml
name: CI

on:
  push:
    branches: [main]
    tags: ["v*"]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  test:
    name: Test & lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
          enable-cache: true
      - name: Install dependencies
        run: uv sync --all-groups --frozen
      - name: Check formatting
        run: uv run ruff format --check src tests
      - name: Lint
        run: uv run ruff check src tests
      - name: Test
        run: uv run pytest

  docker:
    name: Docker image
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Log in to GHCR
        if: startsWith(github.ref, 'refs/tags/v')
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest,enable=${{ startsWith(github.ref, 'refs/tags/v') }}
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ startsWith(github.ref, 'refs/tags/v') }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: YAML parsen**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Workflow-Semantik prüfen**

Run: `docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest`
Expected: keine Ausgabe, Exit-Code 0. Falls das Image nicht gepullt werden kann, stattdessen `go run github.com/rhysd/actionlint/cmd/actionlint@latest` im Repo-Root ausführen.

- [ ] **Step 4: Test- und Lint-Schritte lokal nachstellen**

Run:
```bash
uv sync --all-groups --frozen
uv run ruff format --check src tests
uv run ruff check src tests
uv run pytest
```
Expected: alle drei Prüfungen erfolgreich, `pytest` ohne Fehler.

- [ ] **Step 5: Docker-Build lokal nachstellen**

Run: `docker build -t mcp-server-docker:ci .`
Expected: Build endet mit Exit-Code 0.

- [ ] **Step 6: Ergebnis melden**

Die geänderten Dateien und die Ausgabe der Verifikation zusammenfassen. Kein Commit ohne explizite Anweisung.

## Self-Review

- Spec-Abdeckung: Trigger, Test-Job, Docker-Job, GHCR-Push nur bei Tags, Permissions und Python 3.12 sind je in Task 1 abgebildet.
- Schritt-Scan: Jeder Schritt hat einen prüfbaren Befehl bzw. eine vollständige Datei; keine offenen Platzhalter.
- Typ-/Namens-Konsistenz: Job-Namen `test`/`docker`, Step-IDs `meta`, GHCR-Image `ghcr.io/${{ github.repository }}` sind durchgängig.
- Review Focus: Tag-Erkennung, Fork-PRs und leere Tags sind durch die Bedingungen abgedeckt; der Subprozess-Test durch `setup-uv`; YAML-Semantik durch `actionlint`.
- Proportion: ein Konfigurationsfile, ein Task; der Plan enthält die Datei, weil der exakte Inhalt die Entscheidung ist.
