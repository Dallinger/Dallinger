import json
from datetime import datetime


class ServiceException(Exception):
    """Some error from Recruiter API"""

    pass


def default_study_filter_function(*args, **kwargs):
    return True  # i.e. no filter


class Service(object):
    """Base class for a service that interacts with a recruiter API"""

    @property
    def currency(self):
        raise NotImplementedError

    @property
    def host(self):
        raise NotImplementedError

    def get_account_balance(self):
        """Get account balance"""
        raise NotImplementedError

    def check_credentials(self):
        """Check credentials by making a call to the API"""
        raise NotImplementedError

    def get_qualifications(self, study_id):
        raise NotImplementedError

    def reformat_study(self, study):
        """Reformat a study object from the API"""
        return study

    def get_studies(self, filter=default_study_filter_function, reformat=True):
        """A list of studies by the recruiter."""
        raise NotImplementedError

    def get_study(self, study_id, reformat=True):
        """A single study by the recruiter."""
        raise NotImplementedError

    def reformat_submission(self, submission):
        """Reformat a submission object from the API"""
        return submission

    def get_submissions(self, study_id, reformat=True):
        """A list of submissions for a study."""
        raise NotImplementedError

    def summarize_submissions(self, submissions):
        """
        A summary of submissions for a study.

        This returns a dictionary, where the keys are the names of the summaries, and the values are the summaries.
        For example, this might return a dictionary with the following keys:
        {
            "working": 100,
            "completed": 50,
            "returned": 10,
        }
        """
        raise NotImplementedError

    def summarize_entry_information(self, submissions):
        """
        A summary of entry information from a study.

        This returns a dictionary like this:
        {
            "first_participant_started": "2020-01-01 00:00:00",
            "first_participant_finished": "2020-01-01 00:10:00",
            "last_participant_started": "2020-01-01 02:00:00",
            "last_participant_finished": "2020-01-01 02:13:00",
        }
        """
        raise NotImplementedError

    def _total_completes(self, submission_summary):
        """The total number of completes."""
        raise NotImplementedError

    def get_cost(self, study_id):
        """The cost of a study."""
        total = 0
        for cost in self.get_cost_breakdown(study_id).values():
            total += cost
        return total

    def get_cost_breakdown(self, study_id):
        """
        The cost breakdown of a study.

        This returns a dictionary, where the keys are the names of the costs, and the values are the costs.
        """
        raise NotImplementedError

    def copy_qualifications(self, study_id: str, path: str):
        qualifications = self.get_qualifications(study_id)
        with open(path, "w") as f:
            json.dump(qualifications, f, indent=4)

    def get_relevant_urls(self, study_id):
        """
        A list of relevant URLs for the recruiter

        Returns a dictionary, where the keys are a description/title of the URLs, and the values are the URLs.

        For example, you might want to include an url to the study dashboard of the recruiter (if it exists).
        """
        return None

    def get_wage_per_hour(self, study_id):
        """The wage per hour of a study."""
        return None

    def get_median_completion_time(self, study_id):
        """The median completion time of a study."""
        return None

    def get_summary(self, study_id, metadata=None):
        """A summary of a study."""
        time_started = datetime.now()
        if metadata is None:
            metadata = {}

        study = self.get_study(study_id)

        cost_breakdown = self.get_cost_breakdown(study_id)
        submissions = self.get_submissions(study_id)
        submission_summary = self.summarize_submissions(submissions)
        entry_information = self.summarize_entry_information(submissions)

        # Optional
        urls = self.get_relevant_urls(study_id)
        wage_per_hour = self.get_wage_per_hour(study_id)
        median_completion_time = self.get_median_completion_time(study_id)

        summary = {
            **metadata,
            **study,
            "cost_breakdown": cost_breakdown,
            "total_cost": sum(cost_breakdown.values()),
            "submission_summary": submission_summary,
            "total_submissions": sum(submission_summary.values()),
            "total_completes": self._total_completes(submission_summary),
            "entry_information": entry_information,
            "qualifications": self.get_qualifications(study_id),
            "currency": self.currency,
        }

        if urls:
            summary["urls"] = urls
        if wage_per_hour:
            summary["wage_per_hour"] = wage_per_hour
        if median_completion_time:
            summary["median_completion_time"] = median_completion_time

        time_finished = datetime.now()
        summary["last_updated"] = time_started.strftime("%Y-%m-%d %H:%M:%S")
        summary["time_taken_seconds"] = (time_finished - time_started).total_seconds()

        return summary
