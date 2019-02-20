import os
import pytest

from dallinger import experiments
from dallinger.command_line import verify_package
from dallinger.config import get_config


class TestDemos(object):
    """Verify all the built-in demos."""

    def test_verify_all_demos(self):
        test_root = os.getcwd()
        demo_root = os.path.join("demos", "dlgr", "demos")
        demo_folders = [
            f for f in os.listdir(demo_root) if os.path.isdir(f) and
            not f.startswith('_')
        ]
        for demo in demo_folders:
            demo_path = os.path.join(demo_root, demo)
            os.chdir(demo_path)
            assert verify_package(verbose=False)
            os.chdir(test_root)

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
