def test_serialized(db_session):
    from dallinger.db import serialized
    from dallinger.models import Participant

    counts = []

    # Define a serialized function which writes
    # a row based on a separate query
    def write(session):
        count = session.query(Participant).count()
        counts.append(count)
        session.add(Participant(
            worker_id='serialized_{}'.format(count + 1),
            assignment_id='test',
            hit_id='test',
            mode='test',
        ))
    serialized_write = serialized(write)

    # Make the thread-scoped session SERIALIZABLE and read data with it
    db_session.connection(
        execution_options={'isolation_level': 'SERIALIZABLE'})
    assert Participant.query.count() == 0

    # Now make a change using a separate session
    # that will change the value read above
    session2 = db_session.session_factory()
    session2.connection(
        execution_options={'isolation_level': 'SERIALIZABLE'})
    write(session2)
    session2.commit()

    # Now run the serialized write.
    # It should succeed, but only after retrying the transaction.
    serialized_write(db_session)

    # Which we can check by making sure that `write`
    # calculated the count at least 3 times
    assert counts == [0, 0, 1]
