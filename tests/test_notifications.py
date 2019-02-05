import mock
import pytest


@pytest.fixture
def message():
    return {"subject": "Some subject.", "body": "Some\nmessage"}


class TestEmailConfig(object):
    @pytest.fixture
    def klass(self):
        from dallinger.notifications import EmailConfig

        return EmailConfig

    def test_catches_missing_config_values(self, klass, stub_config):
        stub_config.extend(
            {
                "dallinger_email_address": u"",
                "contact_email_on_error": u"",
                "smtp_username": u"???",
                "smtp_password": u"???",
            }
        )
        econfig = klass(stub_config)
        problems = econfig.validate()
        assert problems == (
            "Missing or invalid config values: contact_email_on_error, "
            "dallinger_email_address, smtp_password, smtp_username"
        )


class TestMessengerFactory(object):
    @pytest.fixture
    def factory(self):
        from dallinger.notifications import get_messenger

        return get_messenger

    def test_returns_debug_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import DebugMessenger

        assert isinstance(factory(stub_config), DebugMessenger)

    def test_returns_emailing_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import EmailingMessenger

        stub_config.extend({"mode": u"sandbox"})
        assert isinstance(factory(stub_config), EmailingMessenger)

    def test_returns_debug_version_if_email_config_invalid(self, factory, stub_config):
        from dallinger.notifications import DebugMessenger

        stub_config.extend({"mode": u"sandbox", "dallinger_email_address": u""})
        assert isinstance(factory(stub_config), DebugMessenger)


class TestDebugMessenger(object):
    @pytest.fixture
    def messenger(self, stub_config):
        from dallinger.notifications import DebugMessenger
        from dallinger.notifications import EmailConfig

        return DebugMessenger(EmailConfig(stub_config))

    def test_logs_message_subject_and_body(self, messenger, message):
        body = message["body"]
        subject = message["subject"]
        with mock.patch("dallinger.notifications.logger") as logger:
            messenger.send(message)
            logger.info.assert_called_once_with(
                "DebugMessenger:\n{}\n{}".format(subject, body)
            )


class TestEmailingMessenger(object):
    @pytest.fixture
    def dummy_mailer(self):
        from smtplib import SMTP
        from dallinger import notifications

        server = mock.create_autospec(SMTP)
        orig_server = notifications.get_email_server
        notifications.get_email_server = mock.Mock(return_value=server)
        yield server
        notifications.get_email_server = orig_server

    @pytest.fixture
    def messenger(self, stub_config):
        from dallinger.notifications import EmailingMessenger
        from dallinger.notifications import EmailConfig

        return EmailingMessenger(EmailConfig(stub_config))

    def test_send_negotiates_email_server(self, messenger, dummy_mailer, message):
        messenger.send(message)

        assert messenger.server is dummy_mailer
        messenger.server.starttls.assert_called()
        messenger.server.login.assert_called_once_with(
            "fake email username", "fake email password"
        )
        messenger.server.sendmail.assert_called()
        messenger.server.quit.assert_called()
        assert messenger.server.sendmail.call_args[0][0] == u"test@example.com"
        assert messenger.server.sendmail.call_args[0][1] == u"error_contact@test.com"

    def test_wraps_mail_server_exceptions(self, messenger, dummy_mailer, message):
        import smtplib
        from dallinger.notifications import MessengerError

        dummy_mailer.login.side_effect = smtplib.SMTPException("Boom!")
        with pytest.raises(MessengerError) as ex_info:
            messenger.send(message)
        assert ex_info.match("SMTP error")

        dummy_mailer.login.side_effect = Exception("Boom!")
        with pytest.raises(MessengerError) as ex_info:
            messenger.send(message)
        assert ex_info.match("Unknown error")
