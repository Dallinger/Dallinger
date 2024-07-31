from unittest import mock

import pytest

study_request = {
    "completion_code": "A1B2C3D4",
    "completion_option": "url",
    "description": "fake HIT description",
    "device_compatibility": ["desktop"],
    "eligibility_requirements": [],
    "estimated_completion_time": 5,
    "external_study_url": "https://www.example.com/ad?recruiter=prolific&PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}",
    "internal_name": "fake experiment title (TEST_EXPERIMENT_UID)",
    "maximum_allowed_time": 17,
    "name": "fake experiment title (dlgr-TEST_EXPERIMENT_UI)",
    "peripheral_requirements": ["audio"],
    "prolific_id_option": "url_parameters",
    "reward": 5,
    "total_available_places": 2,
}

# If you need to created a study for testing which targets just your
# own worker, you can add the worker ID to the eligibility_requirements,
# then run test_make_quick_study() (after removing the @pytest.mark.skip)
private_study_request = {
    "completion_code": "A1B2C3D4",
    "completion_option": "url",
    "description": "(Uses allow_list with one ID)",
    "eligibility_requirements": [
        {
            # Add your worker ID here
            "attributes": [{"name": "white_list", "value": []}],
            "_cls": "web.eligibility.models.CustomWhitelistEligibilityRequirement",
        }
    ],
    "estimated_completion_time": 2,
    "external_study_url": "https://dlgr-d25ea4ab-7400-437a.herokuapp.com/ad?recruiter=prolific&PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}",
    "internal_name": "Test Private Study for One",
    "maximum_allowed_time": 10,
    "name": "Test Private Study for One",
    "prolific_id_option": "url_parameters",
    "reward": 25,
    "total_available_places": 1,
}


@pytest.fixture
def subject(prolific_creds):
    from dallinger.prolific import ProlificService
    from dallinger.version import __version__

    referer = f"https://github.com/Dallinger/Dallinger/tests/v{__version__}"

    return ProlificService(
        api_token=prolific_creds["prolific_api_token"],
        api_version=prolific_creds["prolific_api_version"],
        referer_header=referer,
    )


@pytest.mark.skip(reason="Cannot clean up after itself")
def test_make_quick_study(subject):
    subject.published_study(**private_study_request)


@pytest.mark.usefixtures("check_prolific")
@pytest.mark.slow
def test_all_methods_give_informative_error_messages(subject):
    from dallinger.prolific import ProlificServiceException

    subject.api_version = "junk"

    with pytest.raises(ProlificServiceException) as ex_info:
        subject.who_am_i()

    assert ex_info.match('"URL": "https://api.prolific.com/api/junk/users/me/"')


@pytest.mark.usefixtures("check_prolific")
@pytest.mark.slow
def test_who_am_i_returns_user_info(subject):
    result = subject.who_am_i()

    assert "id" in result


@pytest.mark.usefixtures("check_prolific")
@pytest.mark.slow
def test_requests_are_logged(subject):
    with mock.patch("dallinger.prolific.logger") as logger:
        subject.who_am_i()

    logger.warning.assert_called_once_with(
        'Prolific API request: {"URL": "https://api.prolific.com/api/v1/users/me/", "method": "GET", "args": {}}'
    )


@pytest.mark.usefixtures("check_prolific_writes")
@pytest.mark.slow
def test_can_create_a_draft_study_and_delete_it(subject):
    result = subject.draft_study(**study_request)

    assert "id" in result
    assert subject.delete_study(study_id=result["id"])


@pytest.mark.usefixtures("check_prolific_writes")
@pytest.mark.slow
def test_can_add_to_available_place_count(subject):
    result = subject.draft_study(**study_request)
    initial_spaces = result["total_available_places"]

    # So far, I haven't had to sleep here before trying to fetch the study
    updated = subject.add_participants_to_study(study_id=result["id"], number_to_add=1)

    assert updated["total_available_places"] == initial_spaces + 1
    assert subject.delete_study(study_id=result["id"])
