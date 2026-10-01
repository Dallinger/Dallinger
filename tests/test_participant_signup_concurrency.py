"""Tests for concurrency problems in Dallinger participant signup.

Test structure
--------------

Temporary characterization / reproducer (delete once the fix lands):

  TestSignupRace
    Demonstrates the raw write-skew by calling the database logic directly,
    bypassing Flask and all retry machinery. This test will STILL FAIL after
    the fix because _signup_direct() is intentionally unprotected — it exists
    to show why the bare sequence is inherently unsafe, not to verify that
    production code uses a mutex. Delete it when the fix ships.

  TestSignupRetryBackoff
    Goes through the real Flask route and patches random.expovariate to
    assert the current retry backoff is (today) triggered and (after the fix)
    not triggered. These tests characterize the existing mechanism; once the
    retry/sleep path is removed, delete them.

Permanent behavioral regression suite (keep forever):

  TestSignupBehavioralInvariants
    Implementation-independent invariants expressed as causal assertions.
    These tests do not care whether the eventual fix uses a mutex row,
    advisory locks, SELECT FOR UPDATE, or something else. They should
    remain green after any future refactoring of the serialization strategy.

The two problems
----------------

Write-skew — both threads read occupancy before either writes:

  Thread A                   Thread B              DB rows
  ──────────────────────────────────────────────────────────
  COUNT → 0; nonfailed = 1
                             COUNT → 0; nonfailed = 1
  sleep(50ms)                sleep(50ms)
  INSERT participant A
                             INSERT participant B
  is_overrecruited(1)? No → "working"               1 row
                             is_overrecruited(1)? No → "working"
  COMMIT                                            2 rows  ← bug
                             COMMIT

  Fix: hold a narrow occupancy lock across the read→write. Thread B
  waits to acquire it; once Thread A commits and releases the lock,
  Thread B acquires it, its COUNT sees the new row, gets nonfailed = 2,
  and is correctly marked "overrecruited".

Unrelated-write interference — LOCK TABLE EXCLUSIVE blocks all writes:

  Thread A (status update)   Thread B (POST /participant)
  ──────────────────────────────────────────────────────────
  UPDATE row; flush → ROW EXCLUSIVE held
                             LOCK TABLE EXCLUSIVE NOWAIT → fails
  [waiting]                    → sleep ~2s; retry → fails; retry ...
  rollback (lock released)
                             retry eventually succeeds (slowly)

  Fix: signup acquires only a narrow occupancy lock, compatible with
  Thread A's row-level lock.
"""

import os
import threading
import time
from unittest import mock

import pytest

from dallinger import db, models
from dallinger.experiment import Experiment

# Statuses that count toward occupancy, mirroring the route logic.
_NONFAILED = (
    "working",
    "recruiter_submission_started",
    "overrecruited",
    "submitted",
    "approved",
)


# ---------------------------------------------------------------------------
# Custom experiment subclass used by the direct-DB race test.
# The Flask-based tests use ZSlowTestExperiment from
# tests/experiment/dallinger_experiment.py (quorum=1 there too).
# ---------------------------------------------------------------------------


class SlowQuorumExperiment(Experiment):
    """A test-only experiment that allows exactly one participant (quorum=1)
    and pauses for 50 milliseconds when saving each new participant.

    The pause is deliberate. Without it, the two threads in the race test
    might finish so quickly that one completes its database work before the
    other even starts, making them effectively sequential rather than truly
    simultaneous. The pause widens the race window enough to reproduce the
    collision reliably.
    """

    quorum = 1

    def create_participant(self, **kwargs):  # type: ignore[override]
        time.sleep(0.05)
        return super().create_participant(**kwargs)


def _signup_direct(worker_id):
    """Save a new participant directly to the database, with no retry logic.

    This mirrors the steps the real signup route takes:
      1. Count how many participants are already active.
      2. Create a new participant row (SlowQuorumExperiment sleeps here).
      3. Decide whether the new participant is over the quorum limit.
      4. Save and commit.

    Because there is no serialization or locking around these steps, two
    threads calling this function at the same time will each complete step 1
    before either reaches step 2, which is exactly the race we want to show.

    Each thread gets its own private database session (Python keeps a
    separate database connection for each thread), so both threads are
    genuinely making separate database queries and writes at the same time.

    Note: this is a reproducer. It does not include the route's "has this
    worker already participated?" check. For tests that exercise the full
    production path, see TestSignupBehavioralInvariants.
    """
    session = db.session
    try:
        nonfailed = (
            session.query(models.Participant)
            .filter(models.Participant.status.in_(_NONFAILED))
            .count()
        ) + 1

        exp = SlowQuorumExperiment()
        # Pass recruiter_name explicitly to avoid needing active_config for
        # the recruiter lookup branch in Experiment.create_participant.
        participant = exp.create_participant(
            worker_id=worker_id,
            hit_id="hit1",
            assignment_id=f"assign-{worker_id}",
            mode="debug",
            recruiter_name="hotair",
            fingerprint_hash=None,
            entry_information=None,
        )
        session.flush()
        if exp.is_overrecruited(nonfailed):
            participant.status = "overrecruited"
        session.commit()
        return participant.status
    except Exception:
        session.rollback()
        raise
    finally:
        session.remove()


# ---------------------------------------------------------------------------
# Test 1: demonstrate the raw race (no Flask, no @db.serialized)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestSignupRace:
    """Shows the correctness problem: two simultaneous signups can both be
    accepted when only one should be.

    This test skips the Flask web layer and calls the database logic directly,
    so it shows the raw race rather than anything specific to how Dallinger
    retries. It fails today because both threads read the same stale
    participant count and both end up as 'working'.

    This is a reproducer. It demonstrates that the occupancy logic is unsafe
    without a mutex, but it does not verify that Dallinger's signup route
    actually uses one. For regression tests that exercise the full route, see
    TestSignupBehavioralInvariants.
    """

    def test_concurrent_signups_at_quorum_produce_one_working_one_overrecruited(
        self, db_session
    ):
        """When the experiment is full after one person, and two people sign up
        at the same time, exactly one should be marked 'working' and the other
        should be marked 'overrecruited'.

        This test fails today. Here is why: both threads read the participant
        count before either one has written anything. Both see zero existing
        participants, both add one, and both conclude the experiment still has
        room. Both get saved as 'working'. The assertion below sees
        ['working', 'working'] instead of ['overrecruited', 'working'] and fails.
        """
        barrier = threading.Barrier(2)
        statuses = []
        errors = []

        def signup(worker_id):
            try:
                barrier.wait()
                statuses.append(_signup_direct(worker_id))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(f"w{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not any(t.is_alive() for t in threads), "Signup threads deadlocked"

        assert not errors, f"Signup raised exceptions: {errors}"
        assert len(statuses) == 2
        assert sorted(statuses) == ["overrecruited", "working"], (
            f"Expected one 'working' + one 'overrecruited' at quorum boundary, "
            f"got {statuses!r}. Both threads likely saw count=0 before either "
            f"committed (write-skew / missing occupancy mutex)."
        )


# ---------------------------------------------------------------------------
# Test 2: characterize the current retry/backoff behavior (temporary)
# ---------------------------------------------------------------------------


@pytest.fixture
def slow_app(experiment_dir, active_config, env):
    """A Flask app configured to use ZSlowTestExperiment.

    ZSlowTestExperiment is the same as the normal test experiment but sleeps
    50ms inside create_participant. That sleep widens the race window enough
    to reproduce collisions reliably on every run.

    Without the sleep, threads can finish so quickly that Postgres processes
    their requests one after another on its own, with no overlap — meaning no
    collision is ever detected and the tests pass by luck.
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


@pytest.mark.usefixtures("experiment_dir", "db_session")
@pytest.mark.slow
class TestSignupRetryBackoff:
    """Characterizes the current retry/backoff mechanism.

    These tests go through the real Flask route and patch random.expovariate
    to observe whether the retry backoff fires. Today it does; after the fix
    it should not. Once the retry/sleep path is removed from the codebase,
    delete this class — it is tied to the current implementation.
    """

    def _run_concurrent_signups(self, app, n=2):
        """Send n signup requests to the server at the same time and return
        what each request returned and any errors.

        Each thread gets its own HTTP client so their internal state does not
        interfere with each other. All threads wait at a barrier until every
        one of them is ready, then they all send their requests together.
        This reliably creates a collision rather than leaving it up to timing
        luck.
        """
        barrier = threading.Barrier(n)
        results = []
        errors = []

        def signup(idx):
            try:
                client = app.test_client()
                barrier.wait()
                resp = client.post(f"/participant/worker{idx}/hit1/assign{idx}/debug")
                results.append((resp.status_code, resp.get_json()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not any(t.is_alive() for t in threads), "Signup threads deadlocked"

        return results, errors

    def test_contended_signups_complete_without_retry_backoff(
        self, slow_app, active_config
    ):
        """Five simultaneous signups should complete without triggering the
        retry backoff.

        This test fails today. When signups collide, Dallinger's current
        strategy calls random.expovariate(0.5) to pick a retry delay (on
        average about 2 seconds) and then retries. With 5 threads, at least
        4 of them hit that path, so expovariate gets called repeatedly.

        Five threads are used instead of two because with only 2 threads, one
        can sometimes complete its entire signup before the other even tries
        to acquire the lock, so no collision is detected and no retry is
        triggered. With 5 threads all starting together, collisions are
        essentially guaranteed.

        After the fix, the losing signups will wait inside the database for
        the winner to finish (which takes milliseconds), then proceed one at
        a time. No Python retry or sleep is needed, so expovariate is
        never called.
        """
        n = 5
        with mock.patch("dallinger.db.random.expovariate", return_value=0) as backoff:
            results, errors = self._run_concurrent_signups(slow_app, n=n)

        assert not errors, f"Signups raised: {errors}"
        assert len(results) == n
        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from all signups, got {[s for s, _ in results]}"
        )

        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited"] * (n - 1) + ["working"], (
            f"Expected one 'working' + {n - 1} 'overrecruited', got {statuses!r}"
        )

        assert backoff.call_count == 0, (
            f"expovariate was called {backoff.call_count} time(s). "
            f"Signups are still going through the retry/backoff path."
        )

    def test_contended_signups_complete_without_retry_backoff_psynet_config(
        self, slow_app, active_config
    ):
        """Same as the test above, but with the table lock turned off.

        PsyNet (a system built on top of Dallinger) disables the table lock
        because it caused deadlocks in their setup. With the table lock off,
        Dallinger relies on SERIALIZABLE conflicts to abort and retry
        overlapping signups. The conflict detection works, but using
        transaction abort/retry as the normal serialization mechanism is what
        makes this test fail today: the retry-and-backoff path is still
        triggered.

        This variant uses 5 threads instead of 2. With only 2 threads,
        scheduling can sometimes allow one signup to complete before the other
        reaches the conflicting database operation. No collision is detected
        and no retry is triggered. With 5 threads all starting together,
        collisions are essentially guaranteed.

        After the fix, all 5 threads queue up on the occupancy row lock and
        proceed one at a time. Each holds the lock for roughly 50ms (the
        duration of the sleep in ZSlowTestExperiment), so 5 threads take
        about 250ms total, and expovariate is never called.
        """
        active_config.set("lock_table_when_creating_participant", False)

        n = 5
        with mock.patch("dallinger.db.random.expovariate", return_value=0) as backoff:
            results, errors = self._run_concurrent_signups(slow_app, n=n)

        assert not errors, f"Signups raised: {errors}"
        assert len(results) == n
        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from all signups, got {[s for s, _ in results]}"
        )

        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited"] * (n - 1) + ["working"], (
            f"Expected one 'working' + {n - 1} 'overrecruited', got {statuses!r}"
        )

        assert backoff.call_count == 0, (
            f"expovariate was called {backoff.call_count} time(s) (PsyNet config). "
            f"Signups are still going through the retry/backoff path."
        )


# ---------------------------------------------------------------------------
# Test 3: permanent behavioral invariants (implementation-independent)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("experiment_dir", "db_session")
@pytest.mark.slow
class TestSignupBehavioralInvariants:
    """Permanent regression tests that express what must remain true regardless
    of how signup serialization is eventually implemented.

    These tests do not inspect implementation details like random.expovariate
    or time.sleep. They make causal assertions: "this signup completes while
    that unrelated transaction is still open," or "these two concurrent signups
    produce the right statuses." They will survive a future change that removes
    the retry/backoff mechanism entirely.

    Most of these tests pass today — Dallinger's retry path already produces
    the correct result for concurrent signups. They exist so that future
    refactoring can remove the backoff-patched tests above without losing
    correctness coverage.

    The exception is test_signup_not_blocked_by_unrelated_participant_update,
    which fails today: LOCK TABLE IN EXCLUSIVE MODE blocks concurrent writes
    on the participant table, including writes from unrelated operations. An
    update to a submitted participant's status should not prevent a new person
    from signing up.
    """

    def test_signup_not_blocked_by_unrelated_participant_update(
        self, slow_app, active_config
    ):
        """POST /participant should complete even while an unrelated transaction
        has a participant row locked.

        This is the core problem with LOCK TABLE IN EXCLUSIVE MODE. Any open
        transaction that has written to the participant table — including a
        routine status update on an already-submitted participant — holds a
        ROW EXCLUSIVE lock that conflicts with signup's EXCLUSIVE lock. The two operations have nothing to do
        with each other, but one is forced to wait for the other.

        After the fix, signup acquires only a narrow occupancy lock. An
        unrelated participant update does not hold that lock, so signup
        proceeds without waiting.

        Today (LOCK TABLE IN EXCLUSIVE MODE):
          Thread A: UPDATE existing row, flush → holds ROW EXCLUSIVE
          Thread B: LOCK TABLE EXCLUSIVE NOWAIT → fails ✗
                    → sleep ~2s, retry, fail ✗, sleep, retry ...
                    (blocked until Thread A's transaction ends)

        After fix (narrow occupancy lock):
          Thread A: UPDATE existing row, flush → holds ROW EXCLUSIVE
          Thread B: occupancy lock ✓ → INSERT → COMMIT
                    (Thread A's row lock does not conflict)

        The assertion here is causal, not timing: signup_done is an event that
        is only set when the signup thread finishes. We assert that it fires
        while the blocking transaction is still open (release_blocker has not
        been set yet). There is no wall-clock threshold — the timeout on
        signup_done.wait() is only a deadlock guard.
        """
        # Create a participant for Thread A to lock.
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

        # Wait until Thread A has flushed its UPDATE and holds the lock before
        # starting Thread B. This gives a mechanically certain ordering:
        # lock held → start signup → assert signup completes before lock released.
        assert blocker_started.wait(timeout=5), "Blocking transaction did not start"

        tb = threading.Thread(target=do_signup, daemon=True)
        tb.start()

        # release_blocker is NOT set yet, so Thread A is still holding its
        # transaction open. Assert that Thread B finishes anyway.
        # Today this fails: LOCK TABLE EXCLUSIVE NOWAIT is blocked by Thread
        # A's ROW EXCLUSIVE lock, so signup_done is never set within 5s.
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

    def test_concurrent_signups_at_quorum_produce_correct_result(
        self, slow_app, active_config
    ):
        """Two concurrent signups at quorum=1 should produce exactly one
        'working' participant and one 'overrecruited' — regardless of how the
        serialization is implemented.

        This test passes today: Dallinger's retry path eventually produces the
        correct result. It exists so that future changes (including removing
        the backoff mechanism) do not accidentally break this invariant.
        """
        n = 2
        barrier = threading.Barrier(n)
        results = []
        errors = []

        def signup(idx):
            try:
                client = slow_app.test_client()
                barrier.wait()
                resp = client.post(f"/participant/worker{idx}/hit1/assign{idx}/debug")
                results.append((resp.status_code, resp.get_json()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not any(t.is_alive() for t in threads), "Signup threads deadlocked"
        assert not errors, f"Signups raised: {errors}"
        assert len(results) == n
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
        """Same as the test above, but with the table lock turned off.

        PsyNet disables the table lock. This test confirms that concurrent
        signups still produce the correct result under that configuration —
        today and after the fix.
        """
        active_config.set("lock_table_when_creating_participant", False)

        n = 2
        barrier = threading.Barrier(n)
        results = []
        errors = []

        def signup(idx):
            try:
                client = slow_app.test_client()
                barrier.wait()
                resp = client.post(f"/participant/worker{idx}/hit1/assign{idx}/debug")
                results.append((resp.status_code, resp.get_json()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not any(t.is_alive() for t in threads), "Signup threads deadlocked"
        assert not errors, f"Signups raised: {errors}"
        assert len(results) == n
        assert all(s == 200 for s, _ in results), (
            f"Expected HTTP 200 from all signups, got {[s for s, _ in results]}"
        )

        statuses = sorted(d["participant"]["status"] for _, d in results)
        assert statuses == ["overrecruited", "working"], (
            f"Expected one 'working' + one 'overrecruited', got {statuses!r}"
        )

    def test_concurrent_signups_same_worker_id_rejected(self, slow_app, active_config):
        """When the same worker signs up twice at the same moment, exactly one
        should succeed (HTTP 200) and the other should be turned away (HTTP
        403), with only one participant row in the database.

        This test passes today: Dallinger's retry path produces the right
        answer. The test exists to ensure that any future change to the
        serialization mechanism does not break this invariant — regardless of
        how the second request is held back, the duplicate check must still
        reject it.

        The test uses slow_app (50ms sleep in create_participant) to make the
        overlap between the two threads reliable.
        """
        n = 2
        barrier = threading.Barrier(n)
        results = []
        errors = []

        def signup(idx):
            try:
                client = slow_app.test_client()
                barrier.wait()
                resp = client.post(f"/participant/same-worker/hit1/assign{idx}/debug")
                results.append((resp.status_code, resp.get_json()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=signup, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not any(t.is_alive() for t in threads), "Signup threads deadlocked"
        assert not errors, f"Signups raised: {errors}"
        assert len(results) == n

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
