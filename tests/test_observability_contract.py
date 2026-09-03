from pathlib import Path


def test_observability_migration_tracks_run_phase() -> None:
    migration = Path("db/migrations/004_run_observability.sql").read_text()
    assert "run_kind" in migration
    assert "phase" in migration
    assert "phase_detail" in migration
    assert "updated_at" in migration


def test_api_exposes_system_status() -> None:
    source = Path("src/alexios_hermes_control_plane/api/main.py").read_text()
    assert '@app.get("/v1/system/status")' in source
    assert "system_status" in source


def test_worker_registers_phase_activity() -> None:
    source = Path("src/alexios_hermes_control_plane/worker.py").read_text()
    assert "ledger_update_run_phase" in source
