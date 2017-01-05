import os
from dallinger import db


class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    def _make_one(self):
        from demos.bartlett1932.experiment import Bartlett1932
        return Bartlett1932(self._db)

    def setup(self):
        self._db = db.init_db(drop_all=True)
        # This is only needed for Psiturk Config, which loads on import
        os.chdir('demos/bartlett1932')

    def teardown(self):
        self._db.rollback()
        self._db.close()
        os.chdir('../..')

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
