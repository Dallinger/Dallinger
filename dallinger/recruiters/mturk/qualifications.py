from dallinger.recruiters.mturk import (
    LOCALE_REQUIREMENT_ID,
    PERCENTAGE_APPROVED_REQUIREMENT_ID,
)


class MTurkQualificationRequirements(object):
    """Syntactic correctness for MTurk QualificationRequirements"""

    @staticmethod
    def min_approval(percentage):
        return {
            "QualificationTypeId": PERCENTAGE_APPROVED_REQUIREMENT_ID,
            "Comparator": "GreaterThanOrEqualTo",
            "IntegerValues": [percentage],
            "RequiredToPreview": True,
        }

    @staticmethod
    def restrict_to_countries(countries):
        return {
            "QualificationTypeId": LOCALE_REQUIREMENT_ID,
            "Comparator": "EqualTo",
            "LocaleValues": [{"Country": country} for country in countries],
            "RequiredToPreview": True,
        }

    @staticmethod
    def must_have(qualification_id):
        return {
            "QualificationTypeId": qualification_id,
            "Comparator": "Exists",
            "RequiredToPreview": True,
        }

    @staticmethod
    def must_not_have(qualification_id):
        return {
            "QualificationTypeId": qualification_id,
            "Comparator": "DoesNotExist",
            "RequiredToPreview": True,
        }
