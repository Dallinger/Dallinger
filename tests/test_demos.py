import os
import sys

import pytest

from dallinger import experiments
from dallinger.command_line.utils import verify_package
from dallinger.config import get_config


@pytest.mark.slow
class TestDemos(object):
    """Verify all the built-in demos."""

    @pytest.fixture
    def iter_demos(self):
        def _clean_sys_modules():
            to_clear = [k for k in sys.modules if k.startswith("dallinger_experiment")]
            for key in to_clear:
                del sys.modules[key]

        def _demos():
            test_root = os.getcwd()
            demo_root = os.path.join("demos", "dlgr", "demos")
            demo_paths = [
                os.path.join(demo_root, f)
                for f in os.listdir(demo_root)
                if not f.startswith("_")
            ]
            for demo_path in demo_paths:
                os.chdir(demo_path)
                yield demo_path
                _clean_sys_modules()
                os.chdir(test_root)

        demos = _demos()
        return demos

    def test_verify_all_demos(self, iter_demos):
        for demo in iter_demos:
            if not verify_package(verbose=False):
                pytest.fail("{} did not verify!".format(demo))

    def test_instantiation_via_entry_points(self):
        failures = []

        group = "dallinger.experiments"
        if sys.version_info >= (3, 10):
            entry_points = experiments.entry_points(group=group)
        else:
            entry_points = experiments.entry_points().get(group)

        for entry in entry_points:
            try:
                entry.load()()
            except Exception as ex:
                failures.append("{}: {}".format(entry.name, ex))

        if failures:
            pytest.fail(
                "Some demos had problems loading: {}".format(", ".join(failures))
            )


@pytest.mark.usefixtures("bartlett_dir")
class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    @pytest.fixture
    def demo(self, db_session):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932

        get_config().load()
        instance = Bartlett1932(db_session)
        return instance

    def test_networks_holds_single_experiment_node(self, demo):
        assert len(demo.networks()) == 1
        assert "experiment" == demo.networks()[0].role


class TestEntryPointImport(object):
    def test_bartlett1932_entry_point(self):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932 as OrigExp

        from dallinger.experiments import Bartlett1932

        assert Bartlett1932 is OrigExp
