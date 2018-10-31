import pytest
from mock import Mock, MagicMock, patch
from dallinger.pulse import PulseService

@pytest.fixture
def pulse_service():
    return PulseService("https://fake_url", "fake_key", "fake_app")


def fake_activities_get_response():
    return {
        "response": {
            "activities": [
                {
                    "at_location": "http://sws.geonames.org/226074/",
                    "startedAtTime": "2018-07-10T17:16:51+0000^^http://www.w3.org/2001/XMLSchema#dateTime",
                    "wasInfluencedBy": "3270ecd9-5dec-4864-94a4-36752a15e367",
                    "wasStartedBy": "23418bfa-f255-4778-989e-d9ab66308359",
                    "label": "Test",
                    "id": "78f82722-dfd3-4747-a296-f64c2051e1c9",
                    "type": "Project"
                },
                {
                    "startedAtTime": "2018-07-10T17:16:51+0000^^http://www.w3.org/2001/XMLSchema#dateTime",
                    "wasStartedBy": "23418bfa-f255-4778-989e-d9ab66308359",
                    "wasAssociatedWith": "3931db12-d07c-4056-8f5f-b7838c0179dc",
                    "label": "Test",
                    "id": "3270ecd9-5dec-4864-94a4-36752a15e367",
                    "type": "Campaign"
                }
            ],
            "applicationId": "fake_app"
        },
        "statusCode": 200
    }


def fake_campaign_post_response():
    return {
        "response": {
            "projects": [
                {
                    "name": "test",
                    "location": "<us>",
                    "startTime": "2018-07-17T18:29:41+0000",
                    "id": "1d0cd9f4-94f9-438d-aa05-c8865144d0b2",
                    "version": 1,
                    "flow": {
                        "components": [
                            {
                                "appLink": "http://example.com",
                                "facebookPageId": "12345",
                                "imageUrl": "http://example.com/logo.jpg",
                                "name": "test",
                                "id": "f7b443d7-7ed7-40f6-a8e3-21e5b6b9afda",
                                "type": "FacebookAdvertisement",
                                "message": "fake stuff"
                            },
                            {
                                "name": "test",
                                "id": "ebca20b8-9574-499f-9be0-9cdce5a425ee",
                                "type": "FacebookMessengerBot"
                            }
                        ],
                        "name": "test",
                        "id": "574ff271-338b-441b-8293-3da8fd4dce6d"
                    },
                    "status": "activated"
                }
            ],
            "organization": "test_org",
            "name": "test",
            "startTime": "2018-07-17T18:29:41+0000",
            "id": "9551ebb5-744b-4459-bd75-3baf94cbf002",
            "user": "test_user1",
            "status": "activated"
        },
        "statusCode": 202
    }


def fake_campaign_post_payload():
    return {
        "name": "test",
        "projects": [
            {
                "name": "test",
                "location": "<us>",
                "flow": {
                    "components": [
                        {
                            "type": "FacebookAdvertisement",
                            "name": "test",
                            "message": "fake stuff",
                            "appLink": "http://example.com",
                            "imageUrl": "http://example.com/logo.jpg",
                            "facebookPageId": "12345"
                        },
                        {
                            "type": "FacebookMessengerBot",
                            "name": "test"
                        }
                    ],
                    "name": "test"
                },
                "status": "activated",
                "version": 1
            }
        ],
        "status": "activated"
    }


def fake_engage_response():
    return {
        "response": {
            "modified_on": "2018-06-29T13:33:51.413510Z",
            "engaged_count": 1,
            "groups": [],
            "error": None,
            "uuid": "5e27110a-ecac-47fb-9199-f07176abf294",
            "restart_participants": True,
            "created_on": "2018-06-29T13:33:51.413351Z",
            "extra": {
                "message": "The experiment is ready, please click on the URL.",
                "url": "www.example.com"
            },
            "id": 222,
            "flow": {
                "name": "ShareURL",
                "uuid": "faef1894-7159-4e73-b89e-327cdc87840a"
            },
            "contacts": [
                {
                    "name": "Test",
                    "uuid": "ecbd08d2-6fdc-430b-abac-7b1827ae4433"
                }
            ],
            "statusCode": 200,
            "status": "pending"
        },
        "statusCode": 200
    }

class TestPulseService(object):
    @patch('requests.get', return_value=Mock(text='{"test":"fakeresponse"}'))
    def test_get_has_creds(self, mock_get, pulse_service):
        pulse_service.api_get("activity")

        assert mock_get.call_args[0][0] == "https://fake_url/activity"

        headers = {'x-api-key': 'fake_key', 'applicationId': 'fake_app'}

        assert mock_get.call_args[1]['headers'] == headers

    @patch('requests.post', return_value=Mock(text='{"test":"fakeresponse"}'))
    def test_post_has_creds(self, mock_post, pulse_service):
        pulse_service.api_post("activity", {})

        assert mock_post.call_args[0][0] == "https://fake_url/activity"

        headers = {'x-api-key': 'fake_key', 'applicationId': 'fake_app'}

        assert mock_post.call_args[1]['headers'] == headers

    def test_get_existing_activity(self, pulse_service):
        pulse_service.api_get = MagicMock(return_value=fake_activities_get_response())

        assert pulse_service.get_existing_activity() == "78f82722-dfd3-4747-a296-f64c2051e1c9"

    def test_create_campaign(self, pulse_service):
        pulse_service.api_post = MagicMock(return_value=fake_campaign_post_response())

        assert pulse_service.create_campaign(
            "test",
            "fake stuff",
            "us",
            "http://example.com",
            "http://example.com/logo.jpg",
            "12345"
        )

        assert pulse_service.api_post.call_args[0][1] == fake_campaign_post_payload()
        assert pulse_service.project_id == "1d0cd9f4-94f9-438d-aa05-c8865144d0b2"

    def test_recruit(self, pulse_service):
        pulse_service.api_post = MagicMock(return_value=fake_engage_response())
        pulse_service.project_id = "1d0cd9f4-94f9-438d-aa05-c8865144d0b2"

        assert pulse_service.recruit("1234", "http://example.com")

    def test_reward(self, pulse_service):
        pulse_service.api_post = MagicMock(return_value=fake_engage_response())

        assert pulse_service.recruit("1d0cd9f4-94f9-438d-aa05-c8865144d0b2", "tester")