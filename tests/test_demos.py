import os
import pytest
import subprocess

from dallinger import experiments
from dallinger.config import get_config


class TestDemos(object):
    """Verify all the built-in demos."""

    def test_verify_all_demos(self):
        demo_paths = os.listdir(os.path.join("demos", "dlgr", "demos"))
        for demo_path in demo_paths:
            if demo_path == '__pycache__':
                continue
            if os.path.isdir(demo_path):
                os.chdir(demo_path)
                assert subprocess.check_call(["dallinger", "verify"])
                os.chdir("..")

    def test_instantiation_via_entry_points(self):
        failures = []
        for entry in experiments.iter_entry_points(group='dallinger.experiments'):
            try:
                entry.load()()
            except Exception as ex:
                failures.append("{}: {}".format(entry.name, ex))

        if failures:
            pytest.fail(
                "Some demos had problems loading: {}".format(
                    ', '.join(failures)
                )
            )


@pytest.mark.usefixtures('bartlett_dir')
class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    @pytest.fixture
    def demo(self, db_session):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932
        get_config().load()
        return Bartlett1932(db_session)

    def test_networks_holds_single_experiment_node(self, demo):
        assert len(demo.networks()) == 1
        assert u'experiment' == demo.networks()[0].role


class TestEntryPointImport(object):

    def test_bartlett1932_entry_point(self):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932 as OrigExp
        from dallinger.experiments import Bartlett1932

        assert Bartlett1932 is OrigExp
