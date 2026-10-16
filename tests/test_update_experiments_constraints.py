import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "update_experiments_constraints",
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "update_experiments_constraints.py",
)
update_experiments_constraints = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(update_experiments_constraints)


def test_demo_constraint_refresh_upgrades_extra_dependencies(monkeypatch, tmp_path):
    seen = {}

    def fake_generate(extras=None, upgrade=False):
        seen["upgrade"] = upgrade
        seen["cwd"] = Path.cwd()

    monkeypatch.setattr(
        update_experiments_constraints, "generate_constraints", fake_generate
    )
    update_experiments_constraints.refresh_experiment_constraints(tmp_path)
    assert seen == {"upgrade": True, "cwd": tmp_path.resolve()}
