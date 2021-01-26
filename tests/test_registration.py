class TestRegistration(object):
    def test_registration_module(self):
        from dallinger import registration

        assert registration
        assert registration.register
