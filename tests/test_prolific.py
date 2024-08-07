"""Prolific module tests."""

from unittest import mock
from unittest.mock import MagicMock

import pytest

from dallinger.prolific import (
    ProlificServiceNoSuchProject,
    ProlificServiceNoSuchWorkspace,
)

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

# The return value of a call to /api.prolific.com/api/v1/workspaces/.
WORKSPACES_API_RETURN_VALUE = {
    "results": [
        {
            "id": "66b0f1ff97343f3cd6d6b597",
            "title": "My Workspace",
            "description": "This is your initial workspace.",
            "owner": "66b0f1fd97343f3cd6d6b592",
            "users": [
                {
                    "id": "66b0f1fd97343f3cd6d6b592",
                    "name": "John DeRosa",
                    "email": "johnderosa@me.com",
                    "roles": ["WORKSPACE_ADMIN"],
                }
            ],
            "naivety_distribution_rate": None,
            "product": "human",
            "is_trial_workspace": False,
        },
        {
            "id": "66b0f8e34632badef5c8d1db",
            "title": "zippy the pinhead",
            "description": "",
            "owner": "66b0f1fd97343f3cd6d6b592",
            "users": [
                {
                    "id": "66b0f1fd97343f3cd6d6b592",
                    "name": "John DeRosa",
                    "email": "johnderosa@me.com",
                    "roles": [],
                }
            ],
            "naivety_distribution_rate": None,
            "product": "human",
            "is_trial_workspace": False,
        },
    ],
    "_links": {
        "self": {
            "title": "Current",
            "href": "https://api.prolific.com/api/v1/workspaces/",
        },
        "next": {"href": None, "title": "Next"},
        "previous": {"href": None, "title": "Previous"},
        "last": {
            "href": "https://api.prolific.com/api/v1/workspaces/",
            "title": "Last",
        },
    },
    "meta": {"count": 2},
}

# The return value of a call to /api.prolific.com/api/v1/workspaces/:workspace_id/projects/.
PROJECTS_API_RETURN_VALUE = {
    "results": [
        {
            "id": "66b0f1ff97343f3cd6d6b59a",
            "title": "Project",
            "description": "This is your initial project.",
            "owner": "66b0f1fd97343f3cd6d6b592",
            "users": [
                {
                    "id": "66b0f1fd97343f3cd6d6b592",
                    "name": "John DeRosa",
                    "email": "johnderosa@me.com",
                    "roles": ["PROJECT_EDITOR"],
                }
            ],
            "naivety_distribution_rate": None,
        },
        {
            "id": "66b0f923fa279fd68ab7bd54",
            "title": "default ws project",
            "description": "",
            "owner": "66b0f1fd97343f3cd6d6b592",
            "users": [
                {
                    "id": "66b0f1fd97343f3cd6d6b592",
                    "name": "John DeRosa",
                    "email": "johnderosa@me.com",
                    "roles": ["PROJECT_EDITOR"],
                }
            ],
            "naivety_distribution_rate": None,
        },
    ],
    "_links": {
        "self": {
            "title": "Current",
            "href": "https://api.prolific.com/api/v1/workspaces/66b0f1ff97343f3cd6d6b597/projects/",
        },
        "next": {"href": None, "title": "Next"},
        "previous": {"href": None, "title": "Previous"},
        "last": {
            "href": "https://api.prolific.com/api/v1/workspaces/66b0f1ff97343f3cd6d6b597/projects/",
            "title": "Last",
        },
    },
    "meta": {"count": 2},
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


def test_translate_workspace_name_exception(subject):
    """_translate_workspace_name raises ProlificServiceNoSuchWorkspace."""

    # Mock out self._req.
    subject._req = MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    with pytest.raises(ProlificServiceNoSuchWorkspace):
        subject._translate_workspace_name("does not exist")


def test_translate_project_name_exception(subject):
    """_translate_project_name raises ProlificServiceNoSuchProject."""

    # Mock out self._req.
    subject._req = MagicMock(return_value=PROJECTS_API_RETURN_VALUE)

    with pytest.raises(ProlificServiceNoSuchProject):
        subject._translate_project_name("unused", "does not exist")


@pytest.mark.parametrize(
    "test_input, expected",
    [
        # Translate a name into an id.
        ("zippy the pinhead", "66b0f8e34632badef5c8d1db"),
        # Translate an id into an id.
        ("66b0f8e34632badef5c8d1db", "66b0f8e34632badef5c8d1db"),
    ],
)
def test_translate_workspace_name(subject, test_input, expected):
    """_translate_workspace_name returns a workspace id, when called with either a name or an id."""

    # Mock out self._req.
    subject._req = MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    assert subject._translate_workspace_name(test_input) == expected


@pytest.mark.parametrize(
    "test_input, expected",
    [
        # Translate a name into an id.
        ("default ws project", "66b0f923fa279fd68ab7bd54"),
        # Translate an id into an id.
        ("66b0f923fa279fd68ab7bd54", "66b0f923fa279fd68ab7bd54"),
    ],
)
def test_translate_project_name(subject, test_input, expected):
    """_translate_project_name returns a project id, when called with either a name or an id.."""

    # Mock out self._req.
    subject._req = MagicMock(return_value=PROJECTS_API_RETURN_VALUE)

    assert subject._translate_project_name("unused", test_input) == expected


# @pytest.mark.parametrize(
#     "test_input, expected",
#     [
#         ("default ws project", "66b0f923fa279fd68ab7bd54"),
#         ("66b0f923fa279fd68ab7bd54", "66b0f923fa279fd68ab7bd54"),
#     ],
# )
# def test_translate_draft_study(subject, test_input, expected):
# def test_translate_draft_study(subject):
#     """draft_study creates a default workspace when the configuration workspace is not found."""

#     # Mock out self._req.
#     subject._req = MagicMock(return_value=PROJECTS_API_RETURN_VALUE)

#     result = subject.draft_study(**study_request)
#     assert subject._translate_project_name("unused", test_input) == expected
