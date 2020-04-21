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


class TestSMTPMailer(object):
    @pytest.fixture
    def smtp(self):
        from smtplib import SMTP
        from dallinger import notifications

        server = mock.create_autospec(SMTP)
        orig_server = notifications.get_email_server
        notifications.get_email_server = mock.Mock(return_value=server)
        yield server
        notifications.get_email_server = orig_server

    @pytest.fixture
    def mailer(self):
        from dallinger.notifications import SMTPMailer

        return SMTPMailer(host="host", username="username", password="password")

    def test_send_negotiates_email_server(self, mailer, smtp):
        mailer.send(
            subject="Some subject",
            sender="from@example.com",
            recipients=["to@example.com"],
            body="Some\nbody",
        )
        smtp.starttls.assert_called()
        smtp.login.assert_called_once_with("username", "password")
        smtp.send_message.assert_called_once()
        smtp.quit.assert_called()

        assert len(mailer._sent) == 1

    def test_wraps_mail_server_exceptions(self, mailer, smtp):
        import smtplib
        from dallinger.notifications import MessengerError

        smtp.login.side_effect = smtplib.SMTPException("Boom!")
        with pytest.raises(MessengerError) as ex_info:
            mailer.send(
                subject="Some subject",
                sender="from@example.com",
                recipients=["to@example.com"],
                body="Some\nbody",
            )
        assert ex_info.match("SMTP error")

        smtp.login.side_effect = Exception("Boom!")
        with pytest.raises(MessengerError) as ex_info:
            mailer.send(
                subject="Some subject",
                sender="from@example.com",
                recipients=["to@example.com"],
                body="Some\nbody",
            )
        assert ex_info.match("Unknown error")


class TestMailerFactory(object):
    @pytest.fixture
    def factory(self):
        from dallinger.notifications import get_mailer

        return get_mailer

    def test_returns_debug_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import LoggingMailer

        assert isinstance(factory(stub_config), LoggingMailer)

    def test_returns_emailing_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import SMTPMailer

        stub_config.extend({"mode": u"sandbox"})
        assert isinstance(factory(stub_config), SMTPMailer)

    def test_returns_debug_version_if_email_config_invalid(self, factory, stub_config):
        from dallinger.notifications import LoggingMailer

        stub_config.extend({"mode": u"sandbox", "dallinger_email_address": u""})
        assert isinstance(factory(stub_config), LoggingMailer)

    def test_raises_on_invalid_config_in_strict_mode(self, factory, stub_config):
        from dallinger.notifications import InvalidEmailConfig

        stub_config.extend({"mode": u"sandbox", "dallinger_email_address": u""})
        with pytest.raises(InvalidEmailConfig):
            factory(stub_config, strict=True)


class TestMessengerFactory(object):
    @pytest.fixture
    def factory(self):
        from dallinger.notifications import admin_notifier

        return admin_notifier

    def test_returns_debug_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import NotifiesAdminViaLogs

        assert isinstance(factory(stub_config), NotifiesAdminViaLogs)

    def test_returns_emailing_version_if_configured(self, factory, stub_config):
        from dallinger.notifications import NotifiesAdminByEmail

        stub_config.extend({"mode": u"sandbox"})
        assert isinstance(factory(stub_config), NotifiesAdminByEmail)

    def test_returns_debug_version_if_email_config_invalid(self, factory, stub_config):
        from dallinger.notifications import NotifiesAdminViaLogs

        stub_config.extend({"mode": u"sandbox", "dallinger_email_address": u""})
        assert isinstance(factory(stub_config), NotifiesAdminViaLogs)


class TestNotifiesAdminViaLogs(object):
    @pytest.fixture
    def messenger(self, stub_config):
        from dallinger.notifications import NotifiesAdminViaLogs
        from dallinger.notifications import EmailConfig
        from dallinger.notifications import LoggingMailer

        return NotifiesAdminViaLogs(EmailConfig(stub_config), LoggingMailer())

    def test_logs_message_subject_and_body(self, messenger):
        messenger.send(subject="Some subject", body="Some\nbody")
        assert messenger._sent == ["Some subject: Some\nbody"]


class TestNotifiesAdminByEmail(object):
    @pytest.fixture
    def mailer(self):
        from dallinger.notifications import SMTPMailer

        mailer = mock.Mock(spec=SMTPMailer)
        yield mailer

    @pytest.fixture
    def messenger(self, stub_config, mailer):
        from dallinger.notifications import NotifiesAdminByEmail
        from dallinger.notifications import EmailConfig

        return NotifiesAdminByEmail(EmailConfig(stub_config), mailer)

    def test_constructs_full_email_for_mailer(self, messenger, mailer):
        messenger.send(subject="Some subject", body="Some\nbody")
        messenger.mailer.send.assert_called_once_with(
            "Some subject", "test@example.com", ["error_contact@test.com"], "Some\nbody"
        )
