"""Prolific module tests."""

from unittest import mock

import pytest

from dallinger.config import get_config
from dallinger.prolific import (
    ProlificServiceMultipleWorkspacesException,
    ProlificServiceNoSuchProject,
    ProlificServiceNoSuchWorkspaceException,
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
    "is_custom_screening": True,
    "maximum_allowed_time": 17,
    "name": "fake experiment title (dlgr-TEST_EXPERIMENT_UI)",
    "project_name": "My project",
    "peripheral_requirements": ["audio"],
    "prolific_id_option": "url_parameters",
    "reward": 5,
    "total_available_places": 2,
    "workspace": "My Workspace",
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
    "is_custom_screening": True,
    "maximum_allowed_time": 10,
    "name": "Test Private Study for One",
    "project_name": "My project",
    "prolific_id_option": "url_parameters",
    "reward": 25,
    "total_available_places": 1,
    "workspace": "My Workspace",
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
            "title": "exists twice",
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
        {
            "id": "a1a1a1a1a1a1a1a1a1a1a1a1",
            "title": "exists twice",
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
    subject.create_study(**private_study_request)


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
    assert result["is_custom_screening"] is True
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


def test_translate_workspace_does_not_exist_exception(subject):
    """_translate_workspace raises ProlificServiceNoSuchWorkspaceException."""

    # Mock out self._req.
    subject._req = mock.MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    with pytest.raises(ProlificServiceNoSuchWorkspaceException) as exc_info:
        subject._translate_workspace("does not exist")
    assert (
        str(exc_info.value)
        == "No workspace with ID or name 'does not exist' exists. Please select an existing workspace!"
    )


def test_translate_workspace_multiples_exist_exception(subject):
    """_translate_workspace raises ProlificServiceNoSuchWorkspaceException if multiple workspaces with that name exists."""

    # Mock out self._req.
    subject._req = mock.MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    with pytest.raises(ProlificServiceMultipleWorkspacesException) as exc_info:
        subject._translate_workspace("exists twice")
    assert (
        str(exc_info.value)
        == "Multiple workspaces with name 'exists twice' exist (IDs: 66b0f8e34632badef5c8d1db, a1a1a1a1a1a1a1a1a1a1a1a1)"
    )


def test_translate_project_name_exception(subject):
    """_translate_project_name raises ProlificServiceNoSuchProject."""

    # Mock out self._req.
    subject._req = mock.MagicMock(return_value=PROJECTS_API_RETURN_VALUE)

    with pytest.raises(ProlificServiceNoSuchProject):
        subject._translate_project_name("unused", "does not exist")


@pytest.mark.parametrize(
    "test_input_by_id, expected",
    [
        # Translate an id into an id.
        ("66b0f8e34632badef5c8d1db", "66b0f8e34632badef5c8d1db"),
    ],
)
def test_translate_workspace_by_id_success(subject, test_input_by_id, expected):
    """_translate_workspace returns a workspace id, when called with an id."""

    # Mock out self._req.
    subject._req = mock.MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    assert subject._translate_workspace(test_input_by_id) == expected


@pytest.mark.parametrize(
    "test_input_by_name, expected",
    [
        # Translate a name into an id.
        ("My Workspace", "66b0f1ff97343f3cd6d6b597"),
    ],
)
def test_translate_workspace_by_name_success(subject, test_input_by_name, expected):
    """_translate_workspace returns a workspace id, when called with a name."""

    # Mock out self._req.
    subject._req = mock.MagicMock(return_value=WORKSPACES_API_RETURN_VALUE)

    assert subject._translate_workspace(test_input_by_name) == expected


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
    subject._req = mock.MagicMock(return_value=PROJECTS_API_RETURN_VALUE)

    assert subject._translate_project_name("unused", test_input) == expected


@pytest.mark.parametrize(
    # Parameters:
    # - The value of config.prolific_workspace.
    # - The value of config.prolific_project
    # - The value returned from the workspaces API endpoint.
    # - The value returned from the projects API endpoint.
    # - The expected value of the project key in the call to the studies API endpoint.  None means the project
    #   key should not exist.
    "config_workspace, config_project_name, workspaces_api_result, projects_api_result, expected_project_id",
    [
        # config.prolific_project not found in workspaces API endpoint.
        (
            "My Workspace",
            "this project doesn't exist",
            WORKSPACES_API_RETURN_VALUE,
            PROJECTS_API_RETURN_VALUE,
            "deadbeefba5eba11deadfeed",
        ),
        # config.prolific_project found in workspaces API endpoint.
        (
            "My Workspace",
            "default ws project",
            WORKSPACES_API_RETURN_VALUE,
            PROJECTS_API_RETURN_VALUE,
            "66b0f923fa279fd68ab7bd54",
        ),
    ],
)
@pytest.mark.skip(reason="Needs refactoring and fixing of the tests")
def test_translate_draft_study(
    subject,
    config_workspace,
    config_project_name,
    workspaces_api_result,
    projects_api_result,
    expected_project_id,
):
    """draft_study correctly handles missing and supplied workspace names and project names.

    NB. This tests the connections between draft_study, two inferior functions, and the
    configuration.  The mocked-out results returned from ProlificService._req() are *not* what the
    API actually returns.  This was done for expediency.

    """

    def sideeffect(method, endpoint, **kw):
        """This is used to mock out ProlificService._req().

        The if-statement is not generalized.  It's crafted to work only in this test.
        """

        if method == "POST" and "projects" in endpoint:
            # The call is a POST to create a new project within a workspace.
            return {
                "id": "deadbeefba5eba11deadfeed",
                "title": "My project",
                "description": "This project is for...",
                "owner": "60a42f4c693c29420793cb73",
            }

        if method == "POST" and "studies" in endpoint:
            # The call is to POST to create a draft study.
            return kw["json"].get("project")

        if "projects" in endpoint:
            # The call is a GET to the "projects" endpoint.
            return projects_api_result

        # The call is a GET to the "workspaces" endpoint.
        return workspaces_api_result

    # Mock out ProlificService._req.
    subject._req = mock.MagicMock(side_effect=sideeffect)

    # Load the workspace and project names into the config.
    config = get_config()
    config.set("prolific_workspace", config_workspace)
    config.set("prolific_project", config_project_name)
    config.ready = True
    config.write(filter_sensitive=False)

    assert subject.draft_study(**study_request) == expected_project_id
