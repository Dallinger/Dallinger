from unittest import mock

import pytest


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
        db_session.commit()

        redis_publish.assert_called_once_with("test", "test")


def test_create_db_engine_updates_postgresql_scheme():
    old_scheme_uri = "postgres://foo:bar@somehost:5432/blah"
    from dallinger.db import create_db_engine

    engine = create_db_engine(old_scheme_uri)

    assert engine.url.render_as_string().startswith("postgresql://")


def test_create_db_engine_grows_without_limit_but_keeps_only_pool_size():
    from dallinger.db import create_db_engine, db_url

    engine = create_db_engine(db_url, pool_size=2)
    try:
        # More than SQLAlchemy's default overflow of 10, which would block here.
        connections = [engine.connect() for _ in range(15)]
        for connection in connections:
            connection.close()

        assert engine.pool.checkedin() == 2
    finally:
        engine.dispose()


def test_create_db_engine_replaces_connections_the_server_dropped():
    from sqlalchemy import text

    from dallinger.db import create_db_engine, db_url

    engine = create_db_engine(db_url, pool_size=1)
    killer = create_db_engine(db_url)
    try:
        with engine.connect() as connection:
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
        with killer.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()
        killer.dispose()


def test_create_db_engine_reads_a_bounded_pool_from_the_environment(monkeypatch):
    from sqlalchemy.exc import TimeoutError

    from dallinger.db import create_db_engine, db_url

    monkeypatch.setenv("DATABASE_POOL_SIZE", "1")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT", "0.5")
    engine = create_db_engine(db_url)
    try:
        connections = [engine.connect() for _ in range(2)]
        with pytest.raises(TimeoutError):
            engine.connect()
        for connection in connections:
            connection.close()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "name, value",
    [
        ("DATABASE_POOL_SIZE", "many"),
        ("DATABASE_POOL_SIZE", "0"),
        ("DATABASE_POOL_SIZE", "1.5"),
        ("DATABASE_MAX_OVERFLOW", "-2"),
        ("DATABASE_MAX_OVERFLOW", "lots"),
        ("DATABASE_POOL_TIMEOUT", "0"),
        ("DATABASE_POOL_TIMEOUT", "nan"),
    ],
)
def test_create_db_engine_rejects_invalid_pool_settings(monkeypatch, name, value):
    from dallinger.db import create_db_engine, db_url

    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        create_db_engine(db_url)


def test_create_db_engine_arguments_override_the_environment(monkeypatch):
    from dallinger.db import create_db_engine, db_url

    monkeypatch.setenv("DATABASE_POOL_SIZE", "many")
    engine = create_db_engine(db_url, pool_size=3)
    try:
        assert engine.pool.size() == 3
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "argument, value, message",
    [
        ("pool_size", 0, "pool_size must be an integer of at least 1, not 0."),
        (
            "max_overflow",
            -5,
            r"max_overflow must be an integer of at least -1 \(no limit\), not -5.",
        ),
        ("pool_timeout", 0, "pool_timeout must be a number greater than 0, not 0."),
    ],
)
def test_create_db_engine_rejects_invalid_arguments(argument, value, message):
    from dallinger.db import create_db_engine, db_url

    with pytest.raises(ValueError, match=message):
        create_db_engine(db_url, **{argument: value})
