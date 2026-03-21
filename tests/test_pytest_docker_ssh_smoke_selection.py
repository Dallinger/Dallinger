import importlib.util
import inspect
from pathlib import Path


def _load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeConfig:
    def __init__(self, options):
        self.options = options

    def getoption(self, option_name):
        return self.options.get(option_name, False)


class _FakeItem:
    def __init__(self, *keywords):
        self.keywords = {keyword: True for keyword in keywords}
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)

    @property
    def marker_reasons(self):
        return [marker.kwargs.get("reason") for marker in self.markers]


def _conftest_module():
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    return _load_module(conftest_path, "dallinger_test_conftest")


def _integration_module():
    integration_path = Path(__file__).resolve().parent / "test_docker_ssh_integration.py"
    return _load_module(integration_path, "dallinger_docker_ssh_integration_tests")


def test_docker_ssh_smoke_tests_are_skipped_without_flag(monkeypatch):
    conftest_module = _conftest_module()
    monkeypatch.delenv("RUN_DOCKER", raising=False)
    item = _FakeItem("docker_ssh_smoke", "slow", "docker")
    config = _FakeConfig(
        {
            "--runslow": False,
            "--docker-ssh-smoke": False,
        }
    )

    conftest_module.pytest_collection_modifyitems(config, [item])

    assert item.marker_reasons == ["need --docker-ssh-smoke option to run"]


def test_docker_ssh_smoke_flag_bypasses_slow_and_docker_gates(monkeypatch):
    conftest_module = _conftest_module()
    monkeypatch.delenv("RUN_DOCKER", raising=False)
    item = _FakeItem("docker_ssh_smoke", "slow", "docker")
    config = _FakeConfig(
        {
            "--runslow": False,
            "--docker-ssh-smoke": True,
        }
    )

    conftest_module.pytest_collection_modifyitems(config, [item])

    assert item.marker_reasons == []


def test_all_docker_ssh_integration_tests_require_smoke_marker():
    integration_module = _integration_module()
    test_functions = [
        function
        for name, function in inspect.getmembers(integration_module, inspect.isfunction)
        if name.startswith("test_")
    ]

    assert test_functions

    for function in test_functions:
        marks = getattr(function, "pytestmark", [])
        mark_names = {mark.name for mark in marks}
        assert "docker_ssh_smoke" in mark_names, function.__name__
