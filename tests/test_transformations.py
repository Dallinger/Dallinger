from wallace import db, models, transformations


class TestTransformations(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_apply_identity_transformation(self):
        node = models.Node()
        self.db.add(node)
        self.db.commit()

        info = models.Info(origin=node, contents="foo")
        self.db.add(info)
        self.db.commit()

        transformation = transformations.IdentityTransformation(
            info_in=info, node=node)
        info_out = transformation.apply()
        self.db.add(transformation)
        self.db.commit()

        assert info_out.contents == "foo"
