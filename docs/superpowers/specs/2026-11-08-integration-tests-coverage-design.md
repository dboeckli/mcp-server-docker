# Test-Setup: Coverage und Docker-Integrationstests

**Datum:** 2026-11-08  
**Status:** Entwurf zur Freigabe  
**Branch:** `feature/integration-tests`

## Intent und Warum

Aktuell gibt es 13 Unit-Tests mit ca. 91 % Gesamt-Coverage (`server.py` 98 %). Der
Buildx-`ref`/stderr-Bug aus #258 ist trotzdem durchgerutscht, weil `subprocess.run`
vollständig gemockt war und die reale CLI-Grenze nie ausgeführt wurde. Ziel ist
mehr Vertrauen an genau dieser Grenze – nicht eine höhere Coverage-Zahl.

## Ziele

- `pytest-cov` als Dev-Dependency; Coverage-Report und Threshold 90 % in CI
- Kleine Integrationstest-Suite gegen echtes `docker`/`buildx`
- Integrationstests lokal opt-in, in CI als eigener Job
- Keine Netzabhängigkeit, keine destruktiven Operationen, definiertes Cleanup

## Nicht-Ziele

- Voll-E2E über stdio mit Container-Lebenszyklus (pull/run/remove, Netzwerke, Volumes)
- 100 % Coverage oder erzwungene Coverage für `output_schemas.py`
- Windows-spezifische Tests
- Performance- oder Lasttests

## Constraints

- Python 3.12, `uv`, `pytest`/`anyio`
- Docker und Buildx auf dem CI-Runner (`ubuntu-latest`)
- Builds ausschließlich mit `FROM scratch`, keine Registry-Pulls
- Eindeutige Testnamen, Cleanup best-effort, keine Annahmen über vorhandene Build-History

## Gewählter Ansatz (1 + 2)

1. **Coverage:** `pytest-cov` in die Dev-Gruppe. Coverage wird in CI mit
   `--cov --cov-report=term-missing --cov-fail-under=90` aktiviert, nicht per
   Default bei jedem lokalen Lauf. `.coverage` und `htmlcov/` kommen in
   `.gitignore`.
2. **Integrationstests:** Neues Verzeichnis `tests/integration/`, Tests markiert
   mit `@pytest.mark.integration`. Autouse-Skip, wenn `docker`, `buildx` oder der
   Daemon fehlt. Abgedeckte Fälle:
   - `_run_docker` liefert bei `combine_stderr=True` die Logs (stderr) zurück
   - `buildx_logs` mit langem `ref` aus `buildx_history` liefert Logs
   - `buildx_logs` mit nackter Build-ID liefert Logs
   - unbekannter `ref` erzeugt einen klaren Fehler
   - fehlende Docker-CLI erzeugt `RuntimeError`

   Jeder Test erzeugt einen eigenen `FROM scratch`-Build in `tmp_path`, leitet den
   `ref` aus `buildx_history ls` ab, prüft die Ausgabe und räumt Bild und
   Build-Record best-effort auf.

3. **CI:** Der bestehende `test`-Job bleibt schnell (Unit-Tests + Coverage). Ein
   neuer Job `integration` hängt per `needs: test` davon ab und führt
   `uv run pytest -m integration` aus. Er läuft bei PRs und auf `main`.

4. **Dokumentation:** README bekommt einen kurzen Testing-Abschnitt mit den
   Kommandos für Unit-, Integrations- und Coverage-Läufe.

## Risiken

- `buildx history`/`logs` verhält sich je nach Buildx-Version unterschiedlich. Die
  Tests überspringen sich mit klarer Begründung, wenn `buildx history` nicht
  verfügbar ist.
- Der CI-Runner kann eine andere Buildx-Version als der lokale Host haben; die
  Tests dürfen deshalb keine versionsspezifischen Ausgabeformate erwarten.

## Offen für den Builder

- Genaue Fixture-Struktur und Cleanup-Reihenfolge
- Endgültige Coverage-Schwelle (Vorschlag: 90 %)
- Aufteilung der Integrationstests in eine oder mehrere Dateien
