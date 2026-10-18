"""Compare keeping real-time sessions in redis with keeping them in Postgres.

This is a simulation of the engine's store traffic, not the engine. Each
variant runs the same pattern:

- web processes, gevent with psycogreen, add each player's message to the
  session's entries as it arrives, and hand players the views they get
- a runner plays every session in one loop: it waits for entries or the next
  tick, applies them, ticks, saves each session it played in one write, and
  publishes the pass's views through redis pubsub
- each message is kept as an event row in Postgres

The variants differ in where entries and state live:

- ``redis``: entries in a stream per session (``XADD``, one ``XREAD`` across
  them, with the engine's waker), state in a hash, and records in a stream
  that a records writer moves to Postgres every 2 seconds, as the engine's
  records job does
- ``pg-notify``: an entries table, each insert committed with a ``NOTIFY``
  the runner waits for, and state and events written in the transaction that
  deletes the entries it applied
- ``pg-poll``: the same, with the runner polling the entries table every
  ``--poll-interval`` seconds instead of waiting for a ``NOTIFY``

It reports what ``benchmarks/realtime.py`` reports where the simulation has
it: ack latency from the moment a message was due to be sent, view spacing,
tick lateness, view delay, how late messages were written, and each process's
CPU, Postgres's included. ``events_saved`` counts the event rows, so the
variants can be checked for doing the same work, and ``unsent_messages``
counts the messages a web process fell too far behind to write before the
run ended.

It needs what ``benchmarks/realtime.py`` needs, and empties the same
database::

    .venv/bin/python benchmarks/realtime_store_sim.py --output sim.json
"""

import argparse
import json
import math
import os
import random
import select
import socket
import subprocess
import sys
import tempfile
import time

STORES = ("redis", "pg-notify", "pg-poll")

# Seconds players keep listening after they stop sending.
GRACE = 1.0

# Seconds between starting a run's processes and its players sending.
START_TIME = 3.0

RECORDS_INTERVAL = 2.0

#: Seconds the redis runner waits at most, so it notices the run's end.
MAX_WAIT = 0.5

SCHEMA = """
DROP TABLE IF EXISTS sim_entry, sim_event, sim_session;
CREATE TABLE sim_session (id integer PRIMARY KEY, state jsonb, time double precision);
CREATE TABLE sim_entry (
    id bigserial PRIMARY KEY, session_id integer NOT NULL, data jsonb NOT NULL
);
CREATE INDEX ON sim_entry (session_id);
CREATE TABLE sim_event (
    id bigserial PRIMARY KEY,
    session_id integer NOT NULL,
    participant text,
    number integer,
    payload jsonb,
    time double precision
);
"""

VIEWS_CHANNEL = "sim_views"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add = parser.add_argument
    add("--stores", default=",".join(STORES), help="comma-separated variants")
    add("--sessions", type=int, default=20)
    add("--players", type=int, default=4)
    add("--rate", type=float, default=50, help="messages a second per player")
    add("--tick-rate", type=float, default=20)
    add("--duration", type=float, default=30)
    add("--warmup", type=float, default=5)
    add("--views", choices=["on", "off", "both"], default="both")
    add("--web-processes", type=int, default=1)
    add("--poll-interval", type=float, default=0.005)
    add(
        "--database-url",
        default="postgresql://dallinger:dallinger@localhost/dallinger_benchmark",
    )
    add("--output")
    add("--role", help=argparse.SUPPRESS)
    add("--config", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    stores = args.stores.split(",")
    if not set(stores) <= set(STORES):
        parser.error("--stores takes {}".format(", ".join(STORES)))
    if args.rate <= 0 or args.tick_rate <= 0:
        parser.error("--rate and --tick-rate must be positive")
    args.stores = stores
    return args


# --- the web side ----------------------------------------------------------


def run_web(config):
    import gevent.monkey

    gevent.monkey.patch_all()
    import psycogreen.gevent

    psycogreen.gevent.patch_psycopg()
    import gevent
    import psycopg2.pool
    import redis

    store = config["store"]
    rconn = redis.Redis.from_url(config["redis_url"])
    pool = None
    if store != "redis":
        # psycopg2's pool closes connections returned beyond its minimum, and
        # SQLAlchemy's, which Dallinger uses, keeps them.
        size = len(config["players"])
        pool = psycopg2.pool.ThreadedConnectionPool(size, size, config["database_url"])
    start_at, measure_at, stop_at = config["times"]
    players = {}
    for session_id, player, measures_ticks in config["players"]:
        players[player] = {
            "session_id": session_id,
            "measures_ticks": measures_ticks,
            "due": [],
            "acked": -1,
            "last_tick_received": None,
            "last_tick_time": None,
        }
    out = {
        key: [] for key in ("ack", "ack_at", "spacing", "lateness", "delay", "send_lag")
    }
    out.update(sent=0, unsent=0, unacked=0, views=0, errors=[])

    def measuring(moment):
        return measure_at <= moment < stop_at

    def write(session_id, entry):
        data = json.dumps(entry)
        if store == "redis":
            rconn.xadd(
                "sim:{}:entries".format(session_id),
                {"entry": data},
                maxlen=10000,
                approximate=True,
            )
            return
        conn = pool.getconn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sim_entry (session_id, data) VALUES (%s, %s)",
                    (session_id, data),
                )
                if store == "pg-notify":
                    cursor.execute("NOTIFY sim_entries")
            conn.commit()
        finally:
            pool.putconn(conn)

    def play(player, state):
        interval = 1 / config["rate"]
        due = start_at + random.random() * interval
        while due < stop_at:
            if time.time() >= stop_at:
                # A web process that fell behind leaves the rest unsent.
                first = max(due, measure_at)
                out["unsent"] += max(0, math.ceil((stop_at - first) / interval))
                return
            gevent.sleep(max(due - time.time(), 0))
            started = time.time()
            number = len(state["due"])
            state["due"].append(due)
            if measuring(due):
                out["send_lag"].append(started - due)
            try:
                write(
                    state["session_id"],
                    {"participant": player, "number": number, "move": [1, 0]},
                )
            except Exception as error:
                out["errors"].append(repr(error))
                return
            due += interval

    def listen():
        pubsub = rconn.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(VIEWS_CHANNEL)
        while time.time() < stop_at + GRACE:
            message = pubsub.get_message(timeout=0.2)
            if message is None:
                continue
            received = time.time()
            for item in json.loads(message["data"])["items"]:
                state = players.get(item["participant"])
                if state is not None:
                    take_view(state, item["view"], received)
        pubsub.close()

    def take_view(state, view, received):
        out["views"] += 1
        processed = view["last_processed"]
        if processed is not None and processed > state["acked"]:
            for number in range(state["acked"] + 1, processed + 1):
                due = state["due"][number]
                if measuring(due):
                    out["ack"].append(received - due)
                    out["ack_at"].append(due)
            state["acked"] = processed
        if not measuring(received):
            if view["kind"] == "tick":
                state["last_tick_received"] = received
                state["last_tick_time"] = view["time"]
            return
        out["delay"].append(received - view["clock"])
        if view["kind"] != "tick":
            return
        if state["last_tick_received"] is not None:
            out["spacing"].append(received - state["last_tick_received"])
            if state["measures_ticks"]:
                rate = config["tick_rate"]
                first = (math.floor(state["last_tick_time"] * rate + 1e-6) + 1) / rate
                out["lateness"].append(view["time"] - first)
        state["last_tick_received"] = received
        state["last_tick_time"] = view["time"]

    listener = gevent.spawn(listen)
    gevent.joinall([gevent.spawn(play, *each) for each in players.items()])
    listener.join()
    for state in players.values():
        measured = [n for n, due in enumerate(state["due"]) if measuring(due)]
        out["sent"] += len(measured)
        out["unacked"] += sum(n > state["acked"] for n in measured)
    with open(config["result"], "w") as file:
        json.dump(out, file)


# --- the runner ------------------------------------------------------------


class Session:
    """A simulated session. Times are on the session's clock, which starts
    at 0, since seconds since 1970 are too large a float to place ticks on
    exactly.
    """

    def __init__(self, session_id, players, tick_rate):
        self.id = session_id
        self.players = players
        self.state = {"positions": {player: [0, 0] for player in players}, "ticks": 0}
        self.last_processed = {player: None for player in players}
        self.next_tick = 1 / tick_rate
        self.time = 0
        self.position = "0-0"


class RedisEntries:
    def __init__(self, config):
        import redis

        from dallinger.realtime.store import _waker

        self.redis = redis.Redis.from_url(config["redis_url"])
        self.waker = _waker

    def read(self, sessions, timeout):
        streams = {
            "sim:{}:entries".format(session.id): session.position
            for session in sessions.values()
        }
        block = max(1, round(timeout * 1000)) if timeout > 0 else None
        if block is not None:
            self.waker.arm(time.monotonic() + block / 1000)
        try:
            replies = self.redis.xread(streams, block=block) or []
        finally:
            self.waker.disarm()
        read = {}
        for key, items in replies:
            session_id = int(key.decode().split(":")[1])
            sessions[session_id].position = items[-1][0].decode()
            read[session_id] = [json.loads(fields[b"entry"]) for _, fields in items]
        return read

    def save(self, passes):
        with self.redis.pipeline(transaction=False) as pipe:
            for session, records in passes:
                key = "sim:{}".format(session.id)
                pipe.hset(
                    key,
                    mapping={
                        "state": json.dumps(session.state),
                        "position": session.position,
                    },
                )
                for record in records:
                    pipe.xadd(key + ":records", {"record": json.dumps(record)})
            pipe.execute()


class PostgresEntries:
    def __init__(self, config):
        import psycopg2

        self.conn = psycopg2.connect(config["database_url"])
        self.notify = config["store"] == "pg-notify"
        self.poll_interval = config["poll_interval"]
        if self.notify:
            self.listener = psycopg2.connect(config["database_url"])
            self.listener.autocommit = True
            self.listener.cursor().execute("LISTEN sim_entries")

    def wait(self, timeout):
        if self.notify:
            self.listener.poll()
            if not self.listener.notifies:
                select.select([self.listener], [], [], max(timeout, 0))
                self.listener.poll()
            self.listener.notifies.clear()
        else:
            time.sleep(max(min(self.poll_interval, timeout), 0))

    def read(self, sessions, timeout):
        self.wait(timeout)
        with self.conn.cursor() as cursor:
            # Deleting takes every committed entry, whatever order the inserts
            # committed in, which reading past the last id would not.
            cursor.execute(
                "DELETE FROM sim_entry WHERE session_id = ANY(%s) "
                "RETURNING session_id, id, data",
                (list(sessions),),
            )
            rows = cursor.fetchall()
        read = {}
        for session_id, _, data in sorted(rows, key=lambda row: row[1]):
            read.setdefault(session_id, []).append(data)
        return read

    def save(self, passes):
        from psycopg2.extras import execute_batch, execute_values

        with self.conn.cursor() as cursor:
            execute_batch(
                cursor,
                "UPDATE sim_session SET state = %s, time = %s WHERE id = %s",
                [
                    (json.dumps(session.state), session.time, session.id)
                    for session, _ in passes
                ],
            )
            rows = [
                (
                    session.id,
                    record["participant"],
                    record["number"],
                    json.dumps(record["payload"]),
                    record["time"],
                )
                for session, records in passes
                for record in records
            ]
            if rows:
                execute_values(
                    cursor,
                    "INSERT INTO sim_event "
                    "(session_id, participant, number, payload, time) VALUES %s",
                    rows,
                )
        self.conn.commit()


def run_runner(config):
    import redis

    store = RedisEntries(config) if config["store"] == "redis" else None
    store = store or PostgresEntries(config)
    publisher = redis.Redis.from_url(config["redis_url"])
    tick_rate = config["tick_rate"]
    interval = 1 / tick_rate
    start_at, _, stop_at = config["times"]
    origin = start_at - interval
    sessions = {
        session_id: Session(session_id, players, tick_rate)
        for session_id, players in config["sessions"]
    }
    views_on = config["views_on"]
    end = stop_at + GRACE
    while time.time() < end:
        due = origin + min(session.next_tick for session in sessions.values())
        timeout = min(due - time.time(), MAX_WAIT)
        read = store.read(sessions, timeout)
        clock = time.time()
        now = clock - origin
        passes = []
        items = []
        for session in sessions.values():
            entries = read.get(session.id, [])
            if not entries and now < session.next_tick:
                continue
            session.time = now
            records = []
            senders = set()
            for entry in entries:
                player = entry["participant"]
                position = session.state["positions"][player]
                position[0] += entry["move"][0]
                position[1] += entry["move"][1]
                session.last_processed[player] = entry["number"]
                senders.add(player)
                records.append(
                    {
                        "participant": player,
                        "number": entry["number"],
                        "payload": {"move": entry["move"]},
                        "time": session.time,
                    }
                )
            ticked = False
            while session.next_tick <= now:
                session.state["ticks"] += 1
                session.next_tick += interval
                ticked = True
            passes.append((session, records))
            recipients = session.players if ticked else []
            if not ticked and views_on:
                recipients = sorted(senders)
            for player in recipients:
                items.append(
                    {
                        "participant": player,
                        "view": {
                            "kind": "tick" if ticked else "message",
                            "time": session.time,
                            "clock": clock,
                            "last_processed": session.last_processed[player],
                            "view": session.state,
                        },
                    }
                )
        if passes:
            store.save(passes)
        if items:
            publisher.publish(VIEWS_CHANNEL, json.dumps({"items": items}))


def run_records(config):
    """Move each session's records from redis to Postgres every
    :data:`RECORDS_INTERVAL` seconds, as the engine's records job does.
    """
    import psycopg2
    import redis
    from psycopg2.extras import execute_values

    rconn = redis.Redis.from_url(config["redis_url"])
    conn = psycopg2.connect(config["database_url"])
    _, _, stop_at = config["times"]
    session_ids = [session_id for session_id, _ in config["sessions"]]
    while True:
        finishing = time.time() > stop_at + GRACE
        for session_id in session_ids:
            key = "sim:{}:records".format(session_id)
            items = rconn.xrange(key)
            if not items:
                continue
            rows = []
            for _, fields in items:
                record = json.loads(fields[b"record"])
                rows.append(
                    (
                        session_id,
                        record["participant"],
                        record["number"],
                        json.dumps(record["payload"]),
                        record["time"],
                    )
                )
            with conn.cursor() as cursor:
                execute_values(
                    cursor,
                    "INSERT INTO sim_event "
                    "(session_id, participant, number, payload, time) VALUES %s",
                    rows,
                )
            conn.commit()
            rconn.xdel(key, *[entry_id for entry_id, _ in items])
        if finishing:
            return
        time.sleep(RECORDS_INTERVAL)


# --- the orchestrator ------------------------------------------------------


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(check, timeout, what):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for {}.".format(what))
        time.sleep(0.1)


def summary(values, scale=1000):
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def at(fraction):
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return round(ordered[index] * scale, 3)

    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered) * scale, 3),
        "p50": at(0.5),
        "p90": at(0.9),
        "p99": at(0.99),
        "max": round(ordered[-1] * scale, 3),
    }


def worst_by_second(times, values, start, duration):
    worst = [0.0] * math.ceil(duration)
    for moment, value in zip(times, values):
        second = int(moment - start)
        if 0 <= second < len(worst):
            worst[second] = max(worst[second], value)
    return [round(value * 1000, 1) for value in worst]


def cpu_times(processes):
    """CPU seconds used so far by each group of ``processes``, a dict of
    lists of psutil processes, and by Postgres's server processes.
    """
    import psutil

    groups = dict(processes)
    groups["postgres"] = [
        each
        for each in psutil.process_iter(["name"])
        if each.info["name"] == "postgres"
    ]
    totals = {}
    for group, members in groups.items():
        total = 0.0
        for member in members:
            try:
                times = member.cpu_times()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            total += times.user + times.system
        totals[group] = total
    return time.monotonic(), totals


class Simulation:
    def __init__(self, args, directory, redis_url):
        self.args = args
        self.directory = directory
        self.redis_url = redis_url

    def reset(self):
        import psycopg2
        import redis

        redis.Redis.from_url(self.redis_url).flushall()
        conn = psycopg2.connect(self.args.database_url)
        with conn.cursor() as cursor:
            cursor.execute(SCHEMA)
            for session_id in range(1, self.args.sessions + 1):
                cursor.execute(
                    "INSERT INTO sim_session (id, state, time) VALUES (%s, '{}', 0)",
                    (session_id,),
                )
        conn.commit()
        conn.close()

    def events_saved(self):
        import psycopg2

        conn = psycopg2.connect(self.args.database_url)
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM sim_event")
            (count,) = cursor.fetchone()
        conn.close()
        return count

    def start(self, role, config, name):
        import psutil

        path = os.path.join(self.directory, name + ".json")
        with open(path, "w") as file:
            json.dump(config, file)
        log = open(os.path.join(self.directory, name + ".log"), "w")
        process = subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "--role",
                role,
                "--config",
                path,
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        return process, psutil.Process(process.pid)

    def run(self, store, views_on):
        args = self.args
        self.reset()
        sessions = [
            (
                session_id,
                [
                    str((session_id - 1) * args.players + each + 1)
                    for each in range(args.players)
                ],
            )
            for session_id in range(1, args.sessions + 1)
        ]
        players = [
            (session_id, player, player == members[0])
            for session_id, members in sessions
            for player in members
        ]
        start_at = time.time() + START_TIME
        measure_at = start_at + args.warmup
        stop_at = measure_at + args.duration
        common = {
            "store": store,
            "redis_url": self.redis_url,
            "database_url": args.database_url,
            "tick_rate": args.tick_rate,
            "rate": args.rate,
            "times": [start_at, measure_at, stop_at],
        }
        started = {"runner": [], "records": [], "web": []}
        runner = self.start(
            "runner",
            dict(
                common,
                sessions=sessions,
                views_on=views_on,
                poll_interval=args.poll_interval,
            ),
            "runner",
        )
        started["runner"].append(runner)
        if store == "redis":
            started["records"].append(
                self.start("records", dict(common, sessions=sessions), "records")
            )
        results = []
        for each in range(args.web_processes):
            result = os.path.join(self.directory, "web-{}-result.json".format(each))
            results.append(result)
            started["web"].append(
                self.start(
                    "web",
                    dict(
                        common,
                        players=players[each :: args.web_processes],
                        result=result,
                    ),
                    "web-{}".format(each),
                )
            )
        groups = {
            group: [watched for _, watched in members]
            for group, members in started.items()
        }
        groups["redis"] = self.redis_process
        time.sleep(max(measure_at - time.time(), 0))
        before = cpu_times(groups)
        time.sleep(max(stop_at - time.time(), 0))
        after = cpu_times(groups)
        load_average = [round(each, 2) for each in os.getloadavg()]
        drain_started = time.monotonic()
        failed = []
        for name, members in started.items():
            for process, _ in members:
                try:
                    code = process.wait(60)
                except subprocess.TimeoutExpired:
                    process.kill()
                    code = process.wait()
                if code != 0:
                    failed.append(name)
        drain = time.monotonic() - drain_started

        merged = {"ack": [], "ack_at": [], "spacing": [], "lateness": [], "delay": []}
        merged.update(send_lag=[], errors=[], sent=0, unsent=0, unacked=0, views=0)
        for path in results:
            if not os.path.exists(path):
                continue
            with open(path) as file:
                for key, value in json.load(file).items():
                    merged[key] = merged.get(key, 0 if isinstance(value, int) else [])
                    merged[key] += value
        elapsed = after[0] - before[0]
        return {
            "store": store,
            "views_on_messages": views_on,
            "ack_latency_ms": summary(merged["ack"]),
            "ack_latency_max_ms_by_second": worst_by_second(
                merged["ack_at"], merged["ack"], measure_at, args.duration
            ),
            "view_spacing_ms": summary(merged["spacing"]),
            "tick_lateness_ms": summary(merged["lateness"]),
            "view_delay_ms": summary(merged["delay"]),
            "send_lag_ms": summary(merged["send_lag"]),
            "messages_per_second": round(merged["sent"] / args.duration, 1),
            "unsent_messages": merged["unsent"],
            "unacked_messages": merged["unacked"],
            "views_received": merged["views"],
            "events_saved": self.events_saved(),
            "cpu_cores": {
                group: round((after[1][group] - before[1].get(group, 0)) / elapsed, 3)
                for group in after[1]
            },
            "load_average": load_average,
            "seconds_to_finish": round(drain, 2),
            "failed_processes": failed,
            "errors": merged["errors"][:20],
        }


def main(argv=None):
    args = parse_args(argv)
    if args.role:
        with open(args.config) as file:
            config = json.load(file)
        os.environ["REDIS_URL"] = config["redis_url"]
        {"web": run_web, "runner": run_runner, "records": run_records}[args.role](
            config
        )
        return

    import psutil

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from realtime import cpu_model, ensure_database

    output = os.path.abspath(args.output) if args.output else None
    directory = tempfile.mkdtemp(prefix="realtime-store-sim-")
    print("Logs in {}".format(directory), file=sys.stderr)
    redis_port = free_port()
    redis_url = "redis://127.0.0.1:{}".format(redis_port)
    redis_server = subprocess.Popen(
        ["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
    )
    result = {
        "settings": {
            key: getattr(args, key)
            for key in (
                "sessions",
                "players",
                "rate",
                "tick_rate",
                "duration",
                "warmup",
                "web_processes",
                "poll_interval",
            )
        },
        "environment": {"cpu_model": cpu_model(), "cpu_count": os.cpu_count()},
        "runs": [],
    }
    try:
        import redis

        wait_for(lambda: _pings(redis.Redis.from_url(redis_url)), 10, "redis to start")
        ensure_database(args.database_url)
        simulation = Simulation(args, directory, redis_url)
        simulation.redis_process = [psutil.Process(redis_server.pid)]
        views = {"on": [True], "off": [False], "both": [True, False]}[args.views]
        for store in args.stores:
            for views_on in views:
                print(
                    "Run: {}, views on messages {}".format(
                        store, "on" if views_on else "off"
                    ),
                    file=sys.stderr,
                )
                result["runs"].append(simulation.run(store, views_on))
                print(json.dumps(result["runs"][-1], indent=2), file=sys.stderr)
                if output:
                    with open(output, "w") as file:
                        file.write(json.dumps(result, indent=2) + "\n")
    finally:
        redis_server.terminate()
        redis_server.wait()
    if not output:
        print(json.dumps(result, indent=2))


def _pings(client):
    try:
        return client.ping()
    except Exception:
        return False


if __name__ == "__main__":
    main()
