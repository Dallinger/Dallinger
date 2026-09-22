from dallinger.docker.tools import ensure_experiment_workdir_writable


def test_experiment_directories_become_writable_by_the_runtime_user():
    updated = ensure_experiment_workdir_writable("FROM python\nCOPY . /experiment\n")

    assert "mkdir -p /experiment/static" in updated
    assert "chmod a+rwx /experiment /experiment/static" in updated
    assert "chmod -R" not in updated


def test_writable_directory_step_is_not_repeated():
    dockerfile = (
        "FROM python\n"
        "RUN mkdir -p /experiment/static \\\n"
        " && chmod a+rwx /experiment /experiment/static\n"
    )

    assert ensure_experiment_workdir_writable(dockerfile) == dockerfile
