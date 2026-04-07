"""Regression tests for packaging and cross-platform entrypoints."""

from types import SimpleNamespace

from agentforce import autonomous
from agentforce.cli import cli
from agentforce.core.engine import MissionEngine
from agentforce.core.state import MissionState

from tests.core.test_engine import make_engine


def test_autonomous_uses_importable_package_without_linux_source_paths():
    pkg_root = autonomous._ensure_pkg()
    assert (pkg_root / "agentforce" / "core" / "engine.py").exists()


def test_cmd_kill_marks_state_complete(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(cli, "_find_state", lambda mission_id: engine.state_file)

    cli.cmd_kill(SimpleNamespace(id=engine.state.mission_id))

    state = MissionState.load(engine.state_file)
    assert state.completed_at is not None
    assert any(event.event_type == "mission_killed" for event in state.event_log)


def test_mission_engine_create_factory_matches_public_api(tmp_path):
    engine = make_engine(tmp_path)

    recreated = MissionEngine.create(
        spec=engine.spec,
        state_dir=tmp_path / "state-factory",
        memory=engine.memory,
        mission_id="factory-test",
    )

    assert recreated.state.mission_id == "factory-test"
    assert recreated.state_file.exists()
