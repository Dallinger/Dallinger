import os
import subprocess

from dallinger import db


class TestDemos(object):
    """Verify all the built-in demos."""

    def test_verify_all_demos(self):
        demo_paths = os.listdir("demos")
        for demo_path in demo_paths:
            if os.path.isdir(demo_path):
                os.chdir(demo_path)
                assert subprocess.check_call(["dallinger", "verify"])
                os.chdir("..")


class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    def _make_one(self):
        from demos.bartlett1932.experiment import Bartlett1932
        return Bartlett1932(self._db)

    def setup(self):
        self._db = db.init_db(drop_all=True)
        # This is only needed for config, which loads on import
        os.chdir(os.path.join("demos", "bartlett1932"))

    def teardown(self):
        self._db.rollback()
        self._db.close()
        os.chdir(os.path.join("..", ".."))

    def test_instantiation(self):
        demo = self._make_one()
        assert demo is not None

    def test_networks_holds_single_experiment_node(self):
        demo = self._make_one()
        assert len(demo.networks()) == 1
        assert u'experiment' == demo.networks()[0].role


class TestEntryPointImport(object):

    def test_bartlett1932_entry_point(self):
        from demos.bartlett1932.experiment import Bartlett1932 as OrigExp
        from dallinger.experiments import Bartlett1932

        assert Bartlett1932 is OrigExp
