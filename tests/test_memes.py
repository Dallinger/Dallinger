from wallace import models, memes, db


class TestMemes(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_genome(self):
        meme = memes.Genome()
        self.add(meme)

        assert meme.type == "genome"
        assert meme.contents is None

    def test_create_mimeme(self):
        meme = memes.Mimeme()
        self.add(meme)

        assert meme.type == "mimeme"
        assert meme.contents is None
