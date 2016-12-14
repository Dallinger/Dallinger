from dallinger import db


class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    def _make_one(self):
        from demos import Bartlett1932
        return Bartlett1932(self._db)

    def setup(self):
        self._db = db.init_db(drop_all=True)

    def teardown(self):
        self._db.rollback()
        self._db.close()

    def test_instantiation(self):
        demo = self._make_one()
        assert demo is not None

    def test_networks_holds_single_experiment_node(self):
        demo = self._make_one()
        assert len(demo.networks()) == 1
        assert u'experiment' == demo.networks()[0].role


class TestBartlett1932DemoFactory(object):
    """Just a sketch."""

    def _make_one(self):
        from demos.bartlett1932 import build
        return build()

    def setup(self):
        self._db = db.init_db(drop_all=True)

    def teardown(self):
        self._db.rollback()
        self._db.close()

    def test_demo_factory(self):
        from demos.bartlett1932.experiment import Bartlett1932
        demo = self._make_one()

        assert demo is not None
        assert isinstance(demo, Bartlett1932)
