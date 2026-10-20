from unittest import mock


def test_redis():
    from dallinger.db import redis_conn

    assert redis_conn.ping()


def test_serialized(db_session):
    from dallinger.db import serialized
    from dallinger.models import Participant

    counts = []

    # Define a function which adds a new participant
    # with an id based on a database query.
    def add_participant(session, interruptor=None):
        count = session.query(Participant).count()
        counts.append(count)

        # This is for the sake of the test,
        # to let us change the count from a different session
        # on the first try.
        if interruptor:
            interruptor()

        session.add(
            Participant(
                recruiter_id="hotair",
                worker_id="serialized_{}".format(count + 1),
                assignment_id="test",
                hit_id="test",
                mode="test",
            )
        )

    # Define a function to get in the way of our transaction
    # by changing the participant count from another db session
    # the first time that our serialized transaction is called.
    interrupted = []

    def interruptor():
        if not interrupted:
            session2 = db_session.session_factory()
            session2.connection(execution_options={"isolation_level": "SERIALIZABLE"})
            add_participant(session2)
            session2.commit()
            interrupted.append(True)

    # Now define the test function which will try to add
    # a participant using the scoped db session,
    # but will fail the first time due to the interruption.
    @serialized
    def serialized_write():
        add_participant(db_session, interruptor)

    # Now run the serialized write.
    # It should succeed, but only after retrying the transaction.
    serialized_write()

    # Which we can check by making sure that `add_participant`
    # calculated the count at least 3 times
    assert counts == [0, 0, 1]


def test_after_commit_hook(db_session):
    with mock.patch("dallinger.db.redis_conn.publish") as redis_publish:
        from dallinger.db import queue_message

        queue_message("test", "test")
        redis_publish.assert_not_called()
        db_session.commit()

        redis_publish.assert_called_once_with("test", "test")


def test_run_after_commit_waits_for_the_commit(db_session, caplog):
    from dallinger.db import run_after_commit

    calls = []
    run_after_commit(lambda: calls.append("committed"))
    assert calls == []
    db_session.commit()
    assert calls == ["committed"]

    run_after_commit(lambda: calls.append("rolled back"))
    db_session.rollback()
    db_session.commit()
    assert calls == ["committed"]
    assert caplog.records == []

    run_after_commit(lambda: calls.append("closed"))
    run_after_commit(lambda: calls.append("closed"), "starting session 4")
    db_session.close()
    db_session.commit()
    assert calls == ["committed"]
    assert caplog.messages == [
        "Dropped 2 callbacks waiting for a commit, because their transaction "
        "ended without one: starting session 4."
    ]


def test_a_failing_callback_is_logged_and_the_rest_run(db_session, caplog):
    from dallinger.db import run_after_commit
    from dallinger.models import Network

    calls = []
    run_after_commit(lambda: 1 / 0)
    run_after_commit(lambda: calls.append("after the failure"))
    db_session.commit()

    assert calls == ["after the failure"]
    assert "A callback run after a commit failed" in caplog.text
    assert db_session.query(Network).count() == 0


def test_run_after_commit_drops_only_a_rolled_back_savepoints_callbacks(db_session):
    from dallinger.db import run_after_commit
    from dallinger.models import Network

    calls = []
    db_session.add(Network())
    db_session.flush()
    run_after_commit(lambda: calls.append("outer"))
    for name, end in [("rolled back", "rollback"), ("released", "commit")]:
        savepoint = db_session.begin_nested()
        db_session.add(Network())
        db_session.flush()
        run_after_commit(lambda name=name: calls.append(name))
        getattr(savepoint, end)()
    db_session.commit()
    assert calls == ["outer", "released"]

    db_session.add(Network())
    db_session.flush()
    savepoint = db_session.begin_nested()
    run_after_commit(lambda: calls.append("released, then rolled back"))
    savepoint.commit()
    db_session.rollback()
    db_session.commit()
    assert calls == ["outer", "released"]

    outer = db_session.begin_nested()
    inner = db_session.begin_nested()
    run_after_commit(lambda: calls.append("inside a rolled-back savepoint"))
    inner.commit()
    outer.rollback()
    db_session.commit()
    assert calls == ["outer", "released"]


def test_create_db_engine_updates_postgresql_scheme():
    old_scheme_uri = "postgres://foo:bar@somehost:5432/blah"
    from dallinger.db import create_db_engine

    engine = create_db_engine(old_scheme_uri)

    assert engine.url.render_as_string().startswith("postgresql://")
