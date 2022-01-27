import pytest


study_request = {
    "completion_code": "A1B2C3D4",
    "completion_option": "url",
    "description": "fake HIT description",
    "eligibility_requirements": [],
    "estimated_completion_time": 5,
    "external_study_url": "https://www.example.com/ad?recruiter=prolific",
    "internal_name": "fake experiment title (TEST_EXPERIMENT_UID)",
    "maximum_allowed_time": 17,
    "name": "fake experiment title (dlgr-TEST_EXPERIMENT_UI)",
    "prolific_id_option": "url_parameters",
    "reward": 10,
    "status": "UNPUBLISHED",
    "total_available_places": 5,
}


@pytest.fixture
def subject(prolific_creds):
    from dallinger.prolific import ProlificService

    return ProlificService(
        prolific_creds["prolific_api_token"],
        prolific_creds["prolific_api_version"],
    )


@pytest.mark.usefixtures("check_prolific")
@pytest.mark.slow
def test_all_methods_give_informative_error_messages(subject):
    from dallinger.prolific import ProlificServiceException

    subject.api_version = "junk"

    with pytest.raises(ProlificServiceException) as ex_info:
        subject.who_am_i()

    assert ex_info.match('"URL": "https://api.prolific.co/api/junk/users/me/"')


@pytest.mark.usefixtures("check_prolific")
@pytest.mark.slow
def test_who_am_i_returns_user_info(subject):
    result = subject.who_am_i()

    assert "id" in result


@pytest.mark.usefixtures("check_prolific_writes")
@pytest.mark.slow
def test_create_study(subject):
    """Result keys:
    [
    '_links',
    'average_reward_per_hour',
    'average_reward_per_hour_without_adjustment',
    'average_time_taken',
    'completion_code',
    'completion_option',
    'currency_code',
    'date_created',
    'description',
    'device_compatibility',
    'discount_from_coupons',
    'eligibility_requirements',
    'eligible_participant_count',
    'estimated_completion_time',
    'estimated_reward_per_hour',
    'external_study_url',
    'fees_per_submission',
    'fees_percentage',
    'has_had_adjustment',
    'id',
    'internal_name',
    'is_pilot',
    'is_underpaying',
    'last_email_update_sent_datetime',
    'maximum_allowed_time',
    'meta',
    'minimum_reward_per_hour',
    'name',
    'number_of_submissions',
    'peripheral_requirements',
    'pilot_test_steps_state',
    'places_taken',
    'project',
    'prolific_id_option',
    'publish_at',
    'published_at',
    'publisher',
    'quota_requirements',
    'receipt',
    'representative_sample',
    'representative_sample_fee',
    'researcher',
    'reward',
    'reward_level',
    'share_id',
    'stars_remaining',
    'status',
    'study_type',
    'total_available_places',
    'total_cost',
    'total_participant_pool',
    'vat_percentage',
    'workspace']
    """

    result = subject.create_study(**study_request)

    assert "id" in result

    assert subject.delete_study(study_id=result["id"])
