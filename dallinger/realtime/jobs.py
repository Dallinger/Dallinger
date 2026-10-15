"""The jobs runners queue for Dallinger's worker processes."""


def write_records(session_id):
    """The job a runner queues for a session's new records, and once more when
    the session ends. It doesn't write them to Postgres, and they stay in the
    session's records stream in redis.
    """
