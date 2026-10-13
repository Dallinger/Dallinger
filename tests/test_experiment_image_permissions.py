import stat
import subprocess

from dallinger.docker.tools import (
    _EXPERIMENT_WORKDIR_WRITABLE,
    ensure_experiment_workdir_writable,
)


def test_every_experiment_directory_becomes_writable_but_files_do_not(tmp_path):
    root = tmp_path / "experiment"
    (root / "data" / "cache").mkdir(parents=True)
    (root / "experiment.py").write_text("")
    (root / "experiment.py").chmod(0o644)
    command = _EXPERIMENT_WORKDIR_WRITABLE.removeprefix("RUN ").replace(
        "/experiment", str(root)
    )
    subprocess.run(["sh", "-c", command.replace("\\\n", "")], check=True)

    for directory in (root, root / "static", root / "data" / "cache"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    assert stat.S_IMODE((root / "experiment.py").stat().st_mode) == 0o644


def test_writable_directory_step_is_added_once():
    older = "FROM python\nRUN chmod a+rwx /experiment /experiment/static\n"
    updated = ensure_experiment_workdir_writable(older)

    assert updated.endswith(_EXPERIMENT_WORKDIR_WRITABLE)
    assert ensure_experiment_workdir_writable(updated) == updated
