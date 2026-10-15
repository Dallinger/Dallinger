"""Behavioral regression tests for concurrent participant signup.

These tests express what must remain true about POST /participant regardless
of how signup serialization is implemented. They do not inspect Dallinger
internals such as retry counts or sleep durations.

The two primary concurrency properties
--------------------------------------

Write-skew — both threads must not both be admitted as "working":

  Thread A                   Thread B              DB rows
  ──────────────────────────────────────────────────────────
  acquire advisory lock
                             waits
  COUNT → 0; nonfailed = 1
  sleep(50ms)
  INSERT participant A
  COMMIT (lock released)                           1 row
                             acquire advisory lock
                             COUNT → 1; nonfailed = 2
                             INSERT participant B
                             is_overrecruited(2)? Yes → "overrecruited"
                             COMMIT                2 rows  ✓

Unrelated-write non-interference — signup must not be blocked by an
unrelated participant status update:

  Thread A (status update)   Thread B (POST /participant)
  ──────────────────────────────────────────────────────────
  UPDATE row; flush → ROW EXCLUSIVE held
                             advisory lock (unrelated to ROW EXCLUSIVE) ✓
                             COUNT → INSERT → COMMIT ✓
  rollback

Both properties are currently enforced by the PostgreSQL transaction-level
advisory lock in experiment_server.acquire_participant_signup_lock().
"""

import os
import threading
from unittest import mock

import gevent
import gevent.event
import psycogreen.gevent
import psycopg2.extensions
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from dallinger import db, models

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def psycogreen_active():
    """Apply psycogreen for the duration of one test, then restore blocking mode.

    psycogreen works by registering a gevent-aware wait callback with psycopg2.
    Setting the callback to None restores synchronous blocking behavior, so this
    fixture is safe to use in a test suite that otherwise uses OS threads.
    """
    psycogreen.gevent.patch_psycopg()
    yield
    psycopg2.extensions.set_wait_callback(None)


@pytest.fixture
def slow_app(experiment_dir, active_config, env):
    """A Flask app configured to use ZSlowTestExperiment.

    ZSlowTestExperiment is the same as the normal test experiment but sleeps
    50ms inside create_participant. That sleep widens the race window enough
    to reproduce collisions reliably on every run.

    Without the sleep, threads can finish so quickly that Postgres processes
    their requests one after another on its own — meaning no collision is
    detected and the tests pass by luck.
    """
    from dallinger.experiment_server.experiment_server import app, launch
    from dallinger.pytest_dallinger import uncached_jinja_loader

    os.environ["EXPERIMENT_CLASS_NAME"] = "ZSlowTestExperiment"
    try:
        app.root_path = os.getcwd()
        app.jinja_loader = uncached_jinja_loader(app)
        app.config.update({"DEBUG": True, "TESTING": True})
        with db.sessions_scope():
            launch()
        yield app
    finally:
        os.environ.pop("EXPERIMENT_CLASS_NAME", None)
        app._got_first_request = False


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def run_concurrent_requests(app, urls, timeout=15):
    """Send one POST request per URL to the app, all starting simultaneously.

    Each URL gets its own HTTP client. All threads wait at a barrier until
    every one is ready, then fire together. Returns a list of
    (status_code, json_body) tuples in completion order.

    Asserts that all threads finish (no deadlock) and that no thread raised
    an exception.
    """
    barrier = threading.Barrier(len(urls))
    results = []
    errors = []

    def post(url):
        try:
            client = app.test_client()
            barrier.wait(timeout=5)
            response = client.post(url)
            results.append((response.status_code, response.get_json()))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=post, args=(url,)) for url in urls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)

    assert not any(thread.is_alive() for thread in threads), "Signup threads deadlocked"
    assert not errors, f"Signups raised: {errors}"
    assert len(results) == len(urls)

    return results


# ---------------------------------------------------------------------------
# Gevent cooperative-scheduling regression suite
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("db_session")
@pytest.mark.slow
class TestGeventCooperativeness:
    """Verify that psycopg2 lock waits are gevent-cooperative under psycogreen.

    These tests use gevent greenlets directly (no monkey.patch_all) and the
    psycogreen_active fixture, which sets psycopg2's wait callback for one test
    then restores blocking mode. The OS-thread-based tests in
    TestSignupBehavioralInvariants are unaffected.
    """

    def test_post_worker_init_applies_psycogreen(self):
        """post_worker_init registers psycogreen's wait callback with psycopg2.

        Catches regressions where psycogreen is removed from gunicorn.py —
        the gevent cooperative-scheduling test passes regardless because it
        applies psycogreen via fixture; this test catches the deployment gap.
        """
        from dallinger.experiment_server.gunicorn import post_worker_init

        try:
            post_worker_init(worker=None)
            assert psycopg2.extensions.get_wait_callback() is not None, (
                "post_worker_init must register psycogreen's wait callback so "
                "that psycopg2 lock waits are gevent-cooperative in gunicorn workers."
            )
        finally:
            psycopg2.extensions.set_wait_callback(None)

    def test_advisory_lock_wait_does_not_block_other_greenlets(self, psycogreen_active):
        """While one greenlet waits for the advisory lock, others make progress.

        Without psycogreen, pg_advisory_xact_lock parks the OS thread. No other
        greenlet in the process can run until PostgreSQL responds. With psycogreen
        the wait is handed to gevent's hub, so unrelated greenlets proceed normally.

        This is the gevent analogue of test_signup_not_blocked_by_unrelated_participant_update:
        that test uses OS threads and a row lock; this one uses greenlets and the
        advisory lock itself.
        """
        import dallinger.experiment_server.experiment_server as server_mod

        lock_held = gevent.event.Event()
        release_lock = gevent.event.Event()
        unrelated_ran = gevent.event.Event()

        def hold_advisory_lock():
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": server_mod.PARTICIPANT_SIGNUP_LOCK_KEY},
                    )
                    lock_held.set()
                    release_lock.wait()

        def wait_for_advisory_lock():
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                    conn.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": server_mod.PARTICIPANT_SIGNUP_LOCK_KEY},
                    )

        def unrelated_work():
            # A lightweight greenlet that should be schedulable even while
            # another greenlet is blocked waiting for the advisory lock.
            gevent.sleep(0)
            unrelated_ran.set()

        holder = gevent.spawn(hold_advisory_lock)
        assert lock_held.wait(timeout=5), "Lock-holder greenlet did not start"

        waiter = gevent.spawn(wait_for_advisory_lock)
        unrelated = gevent.spawn(unrelated_work)

        # Give the event loop a moment to run unrelated_work.
        # Without psycogreen: waiter's pg_advisory_xact_lock call parks the OS
        # thread; unrelated never gets scheduled.
        # With psycogreen: waiter suspends cooperatively; unrelated runs.
        gevent.sleep(0.1)

        assert unrelated_ran.is_set(), (
            "An unrelated greenlet was blocked while another greenlet waited "
            "for the advisory lock. psycogreen must be active so that "
            "pg_advisory_xact_lock suspends the greenlet cooperatively rather "
            "than parking the OS thread."
        )

        release_lock.set()
        gevent.joinall([holder, waiter, unrelated], timeout=10)


# ---------------------------------------------------------------------------
# Permanent behavioral regression suite
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("experiment_dir", "db_session")
@pytest.mark.slow
class TestSignupBehavioralInvariants:
    """Permanent regression tests for concurrent participant signup.

    These tests make causal assertions about observable outcomes — HTTP status
    codes, participant statuses, row counts — rather than inspecting the
    serialization mechanism. They will remain valid through future changes to
    how signup serialization is implemented.
    """

    def test_signup_not_blocked_by_unrelated_participant_update(self, slow_app):
        """POST /participant completes even while an unrelated transaction has
        a participant row locked.

        An update to a submitted participant's status takes a ROW EXCLUSIVE
        table lock and locks the affected row. The signup advisory lock is
        independent of both, so the two operations do not block each other.

        The assertion is causal, not timing: signup_done is set only when the
        signup thread finishes. We assert it fires while the blocking
        transaction is still open (release_blocker has not been set yet).
        The timeout on signup_done.wait() is only a deadlock guard.
        """
        setup_client = slow_app.test_client()
        setup_resp = setup_client.post(
            "/participant/setup-worker/hit1/setup-assign/debug"
        )
        assert setup_resp.status_code == 200
        existing_id = setup_resp.get_json()["participant"]["id"]

        blocker_started = threading.Event()
        release_blocker = threading.Event()
        signup_done = threading.Event()
        signup_result = {}
        blocker_error = []
        signup_error = []

        def hold_transaction():
            s = db.session
            try:
                s.query(models.Participant).filter_by(id=existing_id).update(
                    {"status": "submitted"}
                )
                s.flush()  # UPDATE sent to Postgres; ROW EXCLUSIVE lock held
                blocker_started.set()
                release_blocker.wait(timeout=15)
                s.rollback()
            except Exception as exc:
                blocker_error.append(exc)
            finally:
                s.remove()

        def do_signup():
            try:
                client = slow_app.test_client()
                resp = client.post("/participant/new-worker/hit1/new-assign/debug")
                signup_result["status_code"] = resp.status_code
            except Exception as exc:
                signup_error.append(exc)
            finally:
                signup_done.set()

        ta = threading.Thread(target=hold_transaction, daemon=True)
        ta.start()

        # Wait until Thread A has flushed its UPDATE and holds the row lock
        # before starting Thread B. This gives a mechanically certain ordering:
        # lock held → start signup → assert signup completes before lock released.
        assert blocker_started.wait(timeout=5), "Blocking transaction did not start"

        tb = threading.Thread(target=do_signup, daemon=True)
        tb.start()

        # release_blocker is NOT set yet — Thread A's transaction is still open.
        # Assert that Thread B finishes anyway.
        completed = signup_done.wait(timeout=5)

        release_blocker.set()
        ta.join(timeout=5)
        tb.join(timeout=5)

        assert not ta.is_alive(), "Blocking transaction thread did not terminate"
        assert not tb.is_alive(), "Signup thread did not terminate"
        assert not blocker_error, f"Hold-transaction thread failed: {blocker_error}"
        assert not signup_error, f"Signup raised: {signup_error}"
        assert completed, (
            "POST /participant did not complete while an unrelated participant "
            "update held its transaction open. An unrelated participant write "
            "should not block signup."
        )
        assert signup_result.get("status_code") == 200

    def test_advisory_lock_times_out_if_holder_hangs(self):
        """A blocked advisory lock times out instead of waiting indefinitely."""
        import dallinger.experiment_server.experiment_server as server_mod

        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def hold_lock():
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": server_mod.PARTICIPANT_SIGNUP_LOCK_KEY},
                    )
                    lock_acquired.set()
                    release_lock.wait(timeout=10)

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        assert lock_acquired.wait(timeout=5), "Lock-holder thread did not start"

        try:
            with mock.patch.object(
                server_mod, "PARTICIPANT_SIGNUP_LOCK_TIMEOUT", "200ms"
            ):
                with pytest.raises(OperationalError) as exc_info:
                    with db.engine.connect() as conn:
                        with conn.begin():
                            server_mod.acquire_participant_signup_lock(conn)

            assert getattr(exc_info.value.orig, "pgcode", None) == "55P03", (
                "Expected PostgreSQL lock_not_available (55P03), "
                f"got {getattr(exc_info.value.orig, 'pgcode', None)!r}"
            )
        finally:
            release_lock.set()
            holder.join(timeout=5)

        assert not holder.is_alive(), "Lock-holder thread did not terminate"

    def test_concurrent_signups_at_quorum_produce_correct_result(self, slow_app):
        """Two concurrent signups at quorum=1 produce exactly one 'working'
        participant and one 'overrecruited'.
        """
        results = run_concurrent_requests(
            slow_app,
            [f"/participant/worker{i}/hit1/assign{i}/debug" for i in range(2)],
            timeout=30,
        )

        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from all signups, got {[s for s, _ in results]}"
        )
        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited", "working"], (
            f"Expected one 'working' + one 'overrecruited', got {statuses!r}"
        )

    def test_concurrent_signups_at_quorum_produce_correct_result_psynet_config(
        self, slow_app, active_config
    ):
        """Same invariant as test_concurrent_signups_at_quorum_produce_correct_result,
        but with the table lock config disabled.

        PsyNet sets lock_table_when_creating_participant=False. The advisory
        lock is always acquired regardless of that config, so the result is
        the same.
        """
        active_config.set("lock_table_when_creating_participant", False)

        results = run_concurrent_requests(
            slow_app,
            [f"/participant/worker{i}/hit1/assign{i}/debug" for i in range(2)],
            timeout=30,
        )

        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from all signups, got {[s for s, _ in results]}"
        )
        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited", "working"], (
            f"Expected one 'working' + one 'overrecruited', got {statuses!r}"
        )

    def test_concurrent_signups_same_worker_id_rejected(self, slow_app):
        """When the same worker signs up twice concurrently, exactly one
        succeeds (HTTP 200) and the other is rejected (HTTP 403), with only
        one participant row in the database.
        """
        results = run_concurrent_requests(
            slow_app,
            [f"/participant/same-worker/hit1/assign{i}/debug" for i in range(2)],
        )

        status_codes = sorted(s for s, _ in results)
        assert status_codes == [200, 403], (
            f"Expected one 200 and one 403, got {status_codes!r}."
        )

        with db.sessions_scope() as s:
            count = (
                s.query(models.Participant).filter_by(worker_id="same-worker").count()
            )
        assert count == 1, (
            f"Expected one participant row for 'same-worker', got {count}."
        )

    def test_repeat_worker_id_allowed_concurrent_signups_serialized_correctly(
        self, slow_app, active_config
    ):
        """When allow_repeat_worker_ids=True, two concurrent signups from the
        same worker with different assignment IDs are both accepted, and
        occupancy is still serialized correctly: one 'working', one
        'overrecruited'.
        """
        active_config.set("allow_repeat_worker_ids", True)

        results = run_concurrent_requests(
            slow_app,
            [f"/participant/repeat-worker/hit1/assign{i}/debug" for i in range(2)],
        )

        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from both signups, got {[s for s, _ in results]}"
        )

        with db.sessions_scope() as s:
            count = (
                s.query(models.Participant).filter_by(worker_id="repeat-worker").count()
            )
        assert count == 2, (
            f"Expected two participant rows for 'repeat-worker', got {count}."
        )

        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited", "working"], (
            f"Expected one 'working' + one 'overrecruited' even with repeated "
            f"worker IDs, got {statuses!r}"
        )

    def test_concurrent_reused_assignment_id_triggers_reassignment(self, slow_app):
        """When two concurrent requests arrive with different worker IDs but
        the same assignment ID, the second request to proceed detects the
        first participant and enqueues an AssignmentReassigned event.
        """
        from dallinger.experiment_server.experiment_server import worker_function

        with mock.patch("dallinger.experiment_server.experiment_server.q") as mock_q:
            results = run_concurrent_requests(
                slow_app,
                [f"/participant/worker{i}/hit1/shared-assign/debug" for i in range(2)],
            )

        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from both signups, got {[s for s, _ in results]}"
        )

        mock_q.enqueue.assert_called_once_with(
            worker_function,
            "AssignmentReassigned",
            None,
            mock.ANY,  # the first participant's ID
        )
