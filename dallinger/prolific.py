import logging

logger = logging.getLogger(__file__)


class ProlificServiceException(Exception):
    """Some error from Prolific"""

    pass


class ProlificService:
    """Wrapper for Prolific REST API"""

    def __init__(self, prolific_api_token: str):
        self.api_token = prolific_api_token

    def create_study(options: dict) -> dict:
        """Create a Study on Prolific, and return info about it."""

        # TODO The work.
        return {}

    def grant_bonus(study_id: str, worker_id: str, amount: float) -> bool:
        """Pay a worker a bonus"""
        amount_str = "{:.2f}".format(amount)

        payload = {
            "study_id": study_id,
            "csv_bonuses": f"{worker_id},{amount_str}\n",  # ? trailing newline?
        }

        logger.info(f"Would be sending bonus request: {payload}")

        # TODO Actually make request, etc.
        return False
