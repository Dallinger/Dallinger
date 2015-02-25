from wallace import networks, agents, db, sources, models


class TestSuperNetwork(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_create_supernetwork(self):
        supernet = networks.SuperNetwork()
        assert isinstance(supernet, networks.SuperNetwork)

        for i in range(4):
            net = networks.Chain()
            self.db.add(net)

        for net in supernet.networks:
            assert isinstance(net, models.Network)

        assert len(supernet.networks) == 4

    def test_add_agent_to_supernet(self):
        supernet = networks.SuperNetwork()

        for i in range(4):
            net = networks.Chain()
            self.db.add(net)

        for i in range(40):
            agent = agents.Agent()
            self.db.add(agent)
            self.db.commit()
            supernet.add_agent(agent)
